"""
WordBank Generator - Flask Web Application

Main entry point for the web application.

API Sources:
- Merriam-Webster Learner's Dictionary: Definitions, POS, Sentences, Phrases
- Merriam-Webster Intermediate Thesaurus: Synonyms, Antonyms
- Datamuse API: Rhymes, Categories
- USF Free Association Norms: Associated words
- BehrouzSohrabi/Emoji + The Noun Project: Images
- Free Dictionary: Fallback
"""

import os
import json
import time
import threading
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file

from .config import VERSION, DATA_DIR
from .utils.session import SessionState
from .generators.wordbank_manager import WordbankManager, WordEntry
from .generators.word_generator import WordGenerator
from .generators.sound_detector import SoundGroupDetector
from .generators.distractor_generator import DistractorGenerator
from .generators.master_wordbank import get_master_wordbank, MasterWordbank
from .fetchers.emoji_fetcher import EmojiFetcher
from .fetchers.frequency_fetcher import FrequencyFetcher
from .fetchers.dictionary_fetcher import DictionaryFetcher, DataSourceMode, RateLimitError
from .fetchers.translation_fetcher import TranslationFetcher
from .fetchers.idiom_fetcher import IdiomFetcher
from .fetchers.category_fetcher import CategoryFetcher
from .fetchers.api_status import get_api_tracker, APIStatus

# Initialize Flask app
app = Flask(__name__, 
            template_folder=str(Path(__file__).parent / 'templates'),
            static_folder=str(Path(__file__).parent / 'static'))
app.secret_key = os.urandom(24)

# Global instances (lazy loaded)
_generator = None
_emoji_fetcher = None
_frequency_fetcher = None
_dictionary_fetcher = None
_translation_fetcher = None
_sound_detector = None
_idiom_fetcher = None
_category_fetcher = None

# Generation state
_gen_state = {
    'status': 'idle',
    'current': 0,
    'total': 0,
    'current_word': '',
    'successful': 0,
    'failed': 0,
    'skipped_approved': 0,
    'log': [],
    'filename': '',
    'error': '',
    'mode': 'mw_preferred',
    'quality_mode': 'strict',
    'api_status': {},
    'rate_limited': False,
    'rate_limit_api': '',
    'rate_limit_reset': '',
    'words_remaining': [],
    'can_resume': False,
    'words_needing_review': [],
}


def get_generator():
    """Get or create word generator instance."""
    global _generator
    if _generator is None:
        _generator = WordGenerator()
    return _generator


def get_emoji_fetcher():
    """Get or create emoji fetcher instance."""
    global _emoji_fetcher
    if _emoji_fetcher is None:
        _emoji_fetcher = EmojiFetcher()
        _emoji_fetcher.fetch()
    return _emoji_fetcher


def get_frequency_fetcher():
    """Get or create frequency fetcher instance."""
    global _frequency_fetcher
    if _frequency_fetcher is None:
        _frequency_fetcher = FrequencyFetcher()
        _frequency_fetcher.fetch()
    return _frequency_fetcher


def get_dictionary_fetcher():
    """Get or create dictionary fetcher instance."""
    global _dictionary_fetcher
    if _dictionary_fetcher is None:
        _dictionary_fetcher = DictionaryFetcher()
    return _dictionary_fetcher


def get_translation_fetcher():
    """Get or create translation fetcher instance."""
    global _translation_fetcher
    if _translation_fetcher is None:
        _translation_fetcher = TranslationFetcher()
    return _translation_fetcher


def get_sound_detector():
    """Get or create sound detector instance."""
    global _sound_detector
    if _sound_detector is None:
        _sound_detector = SoundGroupDetector()
    return _sound_detector


def get_idiom_fetcher():
    """Get or create idiom fetcher instance."""
    global _idiom_fetcher
    if _idiom_fetcher is None:
        _idiom_fetcher = IdiomFetcher()
    return _idiom_fetcher


def get_category_fetcher():
    """Get or create category fetcher instance."""
    global _category_fetcher
    if _category_fetcher is None:
        _category_fetcher = CategoryFetcher()
    return _category_fetcher


# =============================================================================
# ROUTES - GENERATE
# =============================================================================

@app.route('/')
def index():
    """Redirect to generate page."""
    return redirect(url_for('generate'))


@app.route('/generate')
def generate():
    """Generation settings page."""
    files = WordbankManager.list_files()
    
    # Check for saved progress
    tracker = get_api_tracker()
    has_saved_progress = tracker.has_saved_progress()
    saved_progress = tracker.load_progress() if has_saved_progress else None
    
    return render_template('generate.html', 
                          active_tab='generate',
                          files=files,
                          has_saved_progress=has_saved_progress,
                          saved_progress=saved_progress)


@app.route('/api/generate/start', methods=['POST'])
def api_generate_start():
    """Start generation process."""
    global _gen_state
    
    data = request.json
    filename = data.get('filename', 'wordbank_en.json')
    count = int(data.get('count', 50))
    pos_filter = data.get('pos', '') or None
    custom_words = data.get('custom_words', '').strip().split('\n') if data.get('custom_words') else []
    custom_words = [w.strip() for w in custom_words if w.strip()]
    
    # New options
    mode = data.get('mode', 'mw_preferred')
    quality_mode = data.get('quality_mode', 'strict')
    use_master = data.get('use_master_wordbank', True)
    resume = data.get('resume', False)
    
    # Convert mode string to enum
    mode_map = {
        'mw_preferred': DataSourceMode.MW_PREFERRED,
        'free_dictionary_only': DataSourceMode.FREE_DICTIONARY_ONLY,
        'overnight': DataSourceMode.OVERNIGHT,
    }
    data_mode = mode_map.get(mode, DataSourceMode.MW_PREFERRED)
    
    # Reset state
    _gen_state = {
        'status': 'running',
        'current': 0,
        'total': count,
        'current_word': '',
        'successful': 0,
        'failed': 0,
        'skipped_approved': 0,
        'log': [],
        'filename': filename,
        'error': '',
        'mode': mode,
        'quality_mode': quality_mode,
        'api_status': {},
        'rate_limited': False,
        'rate_limit_api': '',
        'rate_limit_reset': '',
        'words_remaining': [],
        'can_resume': False,
        'words_needing_review': [],
    }
    
    def generate_background():
        global _gen_state, _generator
        
        try:
            # Check for resume
            tracker = get_api_tracker()
            words_to_process = []
            
            if resume and tracker.has_saved_progress():
                progress = tracker.load_progress()
                if progress:
                    # Resume from saved progress
                    words_to_process = progress.get('words_remaining', [])
                    _gen_state['log'].append(f"📂 Resuming from saved progress...")
                    _gen_state['log'].append(f"   {len(progress.get('words_completed', []))} already done")
                    _gen_state['log'].append(f"   {len(words_to_process)} remaining")
            
            # Create new generator with specified settings
            _generator = WordGenerator(
                mode=data_mode,
                quality_mode=quality_mode,
                use_master_wordbank=use_master,
            )
            gen = _generator
            
            # If resuming, restore completed words
            if resume and tracker.has_saved_progress():
                progress = tracker.load_progress()
                if progress:
                    for word in progress.get('words_completed', []):
                        gen.generated_words.add(word.lower())
            else:
                gen.reset()
            
            # Update API status
            _gen_state['api_status'] = gen.get_api_status()
            
            mgr = WordbankManager(str(DATA_DIR / filename))
            master = get_master_wordbank('en') if use_master else None
            
            # Get candidate words
            if words_to_process:
                words = words_to_process
            elif custom_words:
                words = custom_words
            else:
                words = gen.get_candidate_words(count * 3)
            
            target = count
            words_remaining = words.copy()
            
            for i, word in enumerate(words):
                if _gen_state['successful'] >= target:
                    break
                
                # Remove from remaining
                if word in words_remaining:
                    words_remaining.remove(word)
                
                _gen_state['current'] = i + 1
                _gen_state['current_word'] = word
                _gen_state['words_remaining'] = words_remaining
                
                try:
                    # Check if word is in master wordbank
                    word_lower = word.lower().strip()
                    if master and master.is_approved(word_lower):
                        approved = master.get_entry(word_lower)
                        if approved:
                            entry = WordEntry.from_dict(approved)
                            mgr.add_entry(entry)
                            _gen_state['successful'] += 1
                            _gen_state['skipped_approved'] += 1
                            _gen_state['log'].append(f"✓ {entry.emoji} {entry.word} (approved)")
                            continue
                    
                    entry = gen.generate_entry(word, pos_filter)
                    
                    if entry:
                        mgr.add_entry(entry)
                        _gen_state['successful'] += 1
                        emoji_display = entry.emoji if entry.emoji else '📷'
                        _gen_state['log'].append(f"✓ {emoji_display} {entry.word} ({entry.partOfSpeech})")
                    else:
                        _gen_state['failed'] += 1
                        _gen_state['log'].append(f"✗ {word} - skipped")
                
                except RateLimitError as e:
                    # Rate limit hit - save progress and stop
                    _gen_state['rate_limited'] = True
                    _gen_state['rate_limit_api'] = e.api_name
                    _gen_state['rate_limit_reset'] = e.reset_time.isoformat() if e.reset_time else ''
                    _gen_state['log'].append(f"⚠️ Rate limit hit: {e.api_name}")
                    _gen_state['log'].append(f"   Reset at: {e.reset_time}")
                    
                    # Save progress
                    gen.save_progress(
                        words_remaining=words_remaining,
                        wordbank_path=str(DATA_DIR / filename),
                        settings={
                            'mode': mode,
                            'quality_mode': quality_mode,
                            'use_master': use_master,
                            'pos_filter': pos_filter,
                            'target_count': count,
                        }
                    )
                    
                    _gen_state['can_resume'] = True
                    _gen_state['status'] = 'rate_limited'
                    
                    # Save what we have so far
                    mgr.save()
                    return
                    
                except Exception as e:
                    _gen_state['failed'] += 1
                    _gen_state['log'].append(f"✗ {word} - {str(e)[:50]}")
                
                # Update API status periodically
                if _gen_state['current'] % 10 == 0:
                    _gen_state['api_status'] = gen.get_api_status()
                
                # Keep log size manageable
                if len(_gen_state['log']) > 50:
                    _gen_state['log'] = _gen_state['log'][-50:]
                
                time.sleep(0.1)
            
            # Get words needing review
            _gen_state['words_needing_review'] = gen.get_words_needing_review()
            
            # Merge master wordbank entries
            if master and master.count() > 0:
                mgr.data = master.merge_into_wordbank(mgr.data)
            
            # Save
            mgr.save()
            
            # Clear saved progress on successful completion
            tracker.clear_progress()
            
            _gen_state['status'] = 'complete'
            _gen_state['api_status'] = gen.get_api_status()
            
        except Exception as e:
            _gen_state['status'] = 'error'
            _gen_state['error'] = str(e)
            import traceback
            traceback.print_exc()
    
    thread = threading.Thread(target=generate_background)
    thread.start()
    
    return jsonify({'success': True})


@app.route('/api/generate/resume', methods=['POST'])
def api_generate_resume():
    """Resume generation from saved progress."""
    tracker = get_api_tracker()
    
    if not tracker.has_saved_progress():
        return jsonify({'success': False, 'error': 'No saved progress to resume'})
    
    progress = tracker.load_progress()
    if not progress:
        return jsonify({'success': False, 'error': 'Could not load progress'})
    
    # Start generation with resume flag
    data = {
        'filename': Path(progress.get('current_wordbank', '')).name,
        'count': progress.get('settings', {}).get('target_count', 50),
        'mode': progress.get('settings', {}).get('mode', 'mw_preferred'),
        'quality_mode': progress.get('settings', {}).get('quality_mode', 'strict'),
        'use_master_wordbank': progress.get('settings', {}).get('use_master', True),
        'resume': True,
    }
    
    # Use the existing start endpoint with resume flag
    return api_generate_start()


@app.route('/api/generate/status')
def api_generate_status():
    """Get generation status."""
    return jsonify(_gen_state)


@app.route('/api/generate/set-mode', methods=['POST'])
def api_generate_set_mode():
    """Change generation mode during generation."""
    global _generator
    
    data = request.json
    mode = data.get('mode', 'mw_preferred')
    
    mode_map = {
        'mw_preferred': DataSourceMode.MW_PREFERRED,
        'free_dictionary_only': DataSourceMode.FREE_DICTIONARY_ONLY,
        'overnight': DataSourceMode.OVERNIGHT,
    }
    
    if mode not in mode_map:
        return jsonify({'success': False, 'error': f'Unknown mode: {mode}'})
    
    if _generator:
        _generator.set_mode(mode_map[mode])
    
    _gen_state['mode'] = mode
    
    return jsonify({'success': True, 'mode': mode})


@app.route('/api/generate/clear-progress', methods=['POST'])
def api_generate_clear_progress():
    """Clear saved progress."""
    tracker = get_api_tracker()
    tracker.clear_progress()
    return jsonify({'success': True})


# =============================================================================
# ROUTES - API STATUS
# =============================================================================

@app.route('/api/status')
def api_status():
    """Get comprehensive API status."""
    tracker = get_api_tracker()
    statuses = tracker.check_all_apis()
    recommendation = tracker.get_recommended_mode()
    
    return jsonify({
        'mw_learners': statuses['mw_learners'].to_dict(),
        'mw_thesaurus': statuses['mw_thesaurus'].to_dict(),
        'free_dictionary': statuses['free_dictionary'].to_dict(),
        'datamuse': statuses['datamuse'].to_dict(),
        'recommendation': recommendation,
        'has_saved_progress': tracker.has_saved_progress(),
    })


@app.route('/api/status/mw')
def api_status_mw():
    """Get detailed Merriam-Webster API status."""
    tracker = get_api_tracker()
    mw_status = tracker.check_mw_learners_auth()
    mw_thes_status = tracker.check_mw_thesaurus_auth()
    
    return jsonify({
        'learners': mw_status.to_dict(),
        'thesaurus': mw_thes_status.to_dict(),
        'recommendation': tracker.get_recommended_mode(),
    })


# =============================================================================
# ROUTES - MASTER WORDBANK
# =============================================================================

@app.route('/api/master/status')
def api_master_status():
    """Get master wordbank status."""
    language = request.args.get('language', 'en')
    master = get_master_wordbank(language)
    
    return jsonify({
        'language': language,
        'count': master.count(),
        'approved_ids': list(master.get_all_approved_ids()),
    })


@app.route('/api/master/approve', methods=['POST'])
def api_master_approve():
    """Approve an entry and add it to the master wordbank."""
    data = request.json
    filename = data.get('file')
    entry_id = data.get('entry_id')
    approved_by = data.get('approved_by', 'curator')
    notes = data.get('notes', '')
    protected_fields = data.get('protected_fields')
    language = data.get('language', 'en')
    
    if not filename or not entry_id:
        return jsonify({'success': False, 'error': 'Missing file or entry_id'})
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return jsonify({'success': False, 'error': 'File not found'})
    
    mgr = WordbankManager(str(filepath))
    entry = mgr.get_entry(entry_id)
    
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found'})
    
    master = get_master_wordbank(language)
    success = master.approve_entry(
        entry=entry,
        approved_by=approved_by,
        notes=notes,
        protected_fields=protected_fields,
    )
    
    if success:
        return jsonify({
            'success': True,
            'message': f"Entry '{entry.get('word')}' approved.",
            'master_count': master.count(),
        })
    else:
        return jsonify({'success': False, 'error': 'Failed to save'})


@app.route('/api/master/remove', methods=['POST'])
def api_master_remove():
    """Remove an entry from the master wordbank."""
    data = request.json
    entry_id = data.get('entry_id')
    language = data.get('language', 'en')
    
    if not entry_id:
        return jsonify({'success': False, 'error': 'Missing entry_id'})
    
    master = get_master_wordbank(language)
    success = master.remove_entry(entry_id)
    
    if success:
        return jsonify({
            'success': True,
            'message': f"Entry '{entry_id}' removed.",
            'master_count': master.count(),
        })
    else:
        return jsonify({'success': False, 'error': 'Entry not found'})


@app.route('/api/master/list')
def api_master_list():
    """List all entries in the master wordbank."""
    language = request.args.get('language', 'en')
    master = get_master_wordbank(language)
    entries = master.export_for_review()
    
    return jsonify({
        'language': language,
        'count': len(entries),
        'entries': entries,
    })


@app.route('/api/master/import', methods=['POST'])
def api_master_import():
    """Import entries from a wordbank into the master wordbank."""
    data = request.json
    filename = data.get('file')
    entry_ids = data.get('entry_ids')
    approved_by = data.get('approved_by', 'import')
    language = data.get('language', 'en')
    
    if not filename:
        return jsonify({'success': False, 'error': 'Missing file'})
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return jsonify({'success': False, 'error': 'File not found'})
    
    master = get_master_wordbank(language)
    imported = master.import_from_wordbank(
        wordbank_path=str(filepath),
        entry_ids=entry_ids,
        approved_by=approved_by,
    )
    
    return jsonify({
        'success': True,
        'imported': imported,
        'master_count': master.count(),
    })


@app.route('/api/master/get/<entry_id>')
def api_master_get(entry_id):
    """Get a specific entry from the master wordbank."""
    language = request.args.get('language', 'en')
    master = get_master_wordbank(language)
    entry_data = master.get_entry_with_metadata(entry_id)
    
    if entry_data:
        return jsonify({'success': True, 'entry': entry_data})
    else:
        return jsonify({'success': False, 'error': 'Entry not found'})


# =============================================================================
# ROUTES - EDIT
# =============================================================================

@app.route('/edit')
@app.route('/edit/<filename>')
@app.route('/edit/<filename>/<int:idx>')
def edit(filename=None, idx=0):
    """Edit wordbank entries."""
    files = WordbankManager.list_files()
    
    if not filename:
        return render_template('edit.html',
                              active_tab='edit',
                              files=files,
                              entry=None)
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return redirect(url_for('edit'))
    
    mgr = WordbankManager(str(filepath))
    total = mgr.count()
    
    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1 if total > 0 else 0
    
    entry = mgr.get_entry_by_index(idx) if total > 0 else None
    
    if entry:
        entry.setdefault('visual', {'emoji': '❓', 'asset': None})
        entry.setdefault('relationships', {'synonyms': [], 'antonyms': [], 'associated': [], 'rhymes': []})
        entry.setdefault('distractors', [])
        entry.setdefault('sentences', [])
    
    return render_template('edit.html',
                          active_tab='edit',
                          files=files,
                          entry=entry,
                          current=idx,
                          total=total,
                          filename=filename,
                          current_file=filename)


# =============================================================================
# ROUTES - TRANSLATE
# =============================================================================

@app.route('/translate')
@app.route('/translate/<filename>')
@app.route('/translate/<filename>/<int:idx>')
def translate(filename=None, idx=0):
    """Translation page."""
    files = WordbankManager.list_files()
    ref_file = request.args.get('ref', '')
    
    if not filename:
        return render_template('translate.html',
                              active_tab='translate',
                              files=files,
                              entry=None)
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return redirect(url_for('translate'))
    
    mgr = WordbankManager(str(filepath))
    total = mgr.count()
    language = mgr.get_language()
    
    if idx < 0:
        idx = 0
    if idx >= total:
        idx = total - 1 if total > 0 else 0
    
    entry = mgr.get_entry_by_index(idx) if total > 0 else None
    ref_entry = None
    
    if entry and ref_file:
        ref_path = DATA_DIR / ref_file
        if ref_path.exists():
            ref_mgr = WordbankManager(str(ref_path))
            ref_entry = ref_mgr.get_entry(entry.get('id', ''))
    
    if entry:
        entry.setdefault('visual', {'emoji': '❓', 'asset': None})
        entry.setdefault('relationships', {'synonyms': [], 'antonyms': [], 'associated': [], 'rhymes': []})
        entry.setdefault('distractors', [])
        entry.setdefault('sentences', [])
    
    return render_template('translate.html',
                          active_tab='translate',
                          files=files,
                          entry=entry,
                          ref_entry=ref_entry,
                          current=idx,
                          total=total,
                          filename=filename,
                          ref_file=ref_file,
                          language=language,
                          current_file=filename)


@app.route('/api/translate/create', methods=['POST'])
def api_translate_create():
    """Create a translation file."""
    data = request.json
    source = data.get('source')
    language = data.get('language')
    output = data.get('output')
    auto_translate = data.get('auto_translate', False)
    
    if not source or not language or not output:
        return jsonify({'success': False, 'error': 'Missing parameters'})
    
    source_path = DATA_DIR / source
    output_path = DATA_DIR / output
    
    if not source_path.exists():
        return jsonify({'success': False, 'error': 'Source file not found'})
    
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
        
        translator = get_translation_fetcher() if auto_translate else None
        
        trans_data = {
            'version': '2.0',
            'language': language,
            'sourceLanguage': source_data.get('language', 'en'),
            'generatedAt': '',
            'generationMethod': 'translation',
            'totalEntries': len(source_data.get('words', [])),
            'words': [],
        }
        
        for entry in source_data.get('words', []):
            trans_entry = {
                'id': entry.get('id'),
                'word': '',
                'partOfSpeech': entry.get('partOfSpeech', 'noun'),
                'category': entry.get('category', ''),
                'definition': '',
                'soundGroup': '',
                'visual': entry.get('visual', {'emoji': '❓', 'asset': None}),
                'relationships': {
                    'synonyms': [],
                    'antonyms': [],
                    'associated': [],
                    'rhymes': [],
                },
                'distractors': [],
                'sentences': [],
                'phrases': [],
                'needsReview': True,
            }
            
            if translator:
                trans_word = translator.translate(entry.get('word', ''), 'en', language)
                if trans_word:
                    trans_entry['word'] = trans_word
                
                trans_def = translator.translate(entry.get('definition', ''), 'en', language)
                if trans_def:
                    trans_entry['definition'] = trans_def
                
                for sentence in entry.get('sentences', [])[:2]:
                    trans_sent = translator.translate(sentence, 'en', language)
                    if trans_sent:
                        trans_entry['sentences'].append(trans_sent)
            
            trans_data['words'].append(trans_entry)
        
        trans_data['generatedAt'] = datetime.now().isoformat()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(trans_data, f, indent=2, ensure_ascii=False)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/translate/services')
def api_translate_services():
    """Check translation service availability."""
    translator = get_translation_fetcher()
    return jsonify(translator.check_services())


# =============================================================================
# ROUTES - API
# =============================================================================

@app.route('/api/emoji/search')
def api_emoji_search():
    """Search for emojis."""
    query = request.args.get('q', '')
    emoji_fetcher = get_emoji_fetcher()
    results = emoji_fetcher.search(query, limit=30)
    return jsonify({'results': results})


@app.route('/api/sound-group')
def api_sound_group():
    """Get sound group for a word."""
    word = request.args.get('word', '')
    detector = get_sound_detector()
    return jsonify({'soundGroup': detector.get_sound_group(word)})


@app.route('/api/category')
def api_category():
    """Get category for a word."""
    word = request.args.get('word', '')
    pos = request.args.get('pos', 'noun')
    
    cat_fetcher = get_category_fetcher()
    category = cat_fetcher.fetch_category(word, pos)
    
    return jsonify({'category': category, 'word': word})


@app.route('/api/distractors', methods=['POST'])
def api_distractors():
    """Generate distractors for a word."""
    data = request.json
    word = data.get('word', '')
    pos = data.get('pos', 'noun')
    avoid = set(data.get('avoid', []))
    rhymes = data.get('rhymes', [])
    category = data.get('category', '')
    
    freq = get_frequency_fetcher()
    dict_fetcher = get_dictionary_fetcher()
    detector = get_sound_detector()
    
    dist_gen = DistractorGenerator(freq, dict_fetcher, detector)
    distractors = dist_gen.generate(word, pos, avoid, rhymes, category)
    
    return jsonify({'distractors': distractors})


@app.route('/api/entry/save', methods=['POST'])
def api_entry_save():
    """Save an entry."""
    filename = request.args.get('file')
    if not filename:
        return jsonify({'success': False, 'error': 'No file specified'})
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return jsonify({'success': False, 'error': 'File not found'})
    
    mgr = WordbankManager(str(filepath))
    data = request.json
    
    entry_id = data.get('id')
    if not entry_id:
        return jsonify({'success': False, 'error': 'No entry ID'})
    
    for entry in mgr.data.get('words', []):
        if entry.get('id') == entry_id:
            entry['word'] = data.get('word', entry.get('word', ''))
            entry['partOfSpeech'] = data.get('partOfSpeech', entry.get('partOfSpeech', 'noun'))
            entry['category'] = data.get('category', entry.get('category', ''))
            entry['soundGroup'] = data.get('soundGroup', entry.get('soundGroup', ''))
            entry['definition'] = data.get('definition', entry.get('definition', ''))
            entry['sentences'] = data.get('sentences', entry.get('sentences', []))
            
            if 'emoji' in data:
                entry.setdefault('visual', {})['emoji'] = data['emoji']
            
            if 'relationships' in data:
                entry['relationships'] = data['relationships']
            
            entry['distractors'] = data.get('distractors', entry.get('distractors', []))
            entry['phrases'] = data.get('phrases', entry.get('phrases', []))
            
            entry['needsReview'] = (
                not entry.get('word') or
                not entry.get('definition') or
                not entry.get('visual', {}).get('emoji') or
                len(entry.get('sentences', [])) < 2 or
                len(entry.get('distractors', [])) < 10
            )
            
            break
    
    mgr.save()
    return jsonify({'success': True})


@app.route('/api/entry/delete', methods=['POST'])
def api_entry_delete():
    """Delete an entry."""
    filename = request.args.get('file')
    if not filename:
        return jsonify({'success': False, 'error': 'No file specified'})
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return jsonify({'success': False, 'error': 'File not found'})
    
    mgr = WordbankManager(str(filepath))
    data = request.json
    entry_id = data.get('id')
    
    mgr.delete_entry(entry_id)
    mgr.save()
    
    return jsonify({'success': True})


@app.route('/download/<filename>')
def download_file(filename):
    """Download a wordbank file."""
    filepath = DATA_DIR / filename
    if filepath.exists():
        return send_file(str(filepath), as_attachment=True)
    return redirect(url_for('generate'))


# =============================================================================
# ROUTES - REVIEW (Words needing manual input)
# =============================================================================

@app.route('/api/review/list')
def api_review_list():
    """Get list of words needing review from last generation."""
    return jsonify({
        'words': _gen_state.get('words_needing_review', []),
        'count': len(_gen_state.get('words_needing_review', [])),
    })


@app.route('/api/review/attribution')
def api_review_attribution():
    """Get words using Noun Project images (need attribution)."""
    emoji_fetcher = get_emoji_fetcher()
    words = emoji_fetcher.get_words_with_attribution()
    
    return jsonify({
        'words': words,
        'count': len(words),
    })


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run the application."""
    print(f"""
╔══════════════════════════════════════════════════════════╗
║         WordBank Generator v{VERSION}                     ║
║   Unified Web App for Speech Therapy Wordbanks           ║
╠══════════════════════════════════════════════════════════╣
║  API Sources:                                            ║
║  • Merriam-Webster Learner's: Definitions, Sentences     ║
║  • Merriam-Webster Thesaurus: Synonyms, Antonyms         ║
║  • Datamuse: Rhymes, Categories                          ║
║  • USF Free Association: Associated words                ║
║  • BehrouzSohrabi/Emoji + Noun Project: Images           ║
╠══════════════════════════════════════════════════════════╣
║  Data directory: {str(DATA_DIR):<40} ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    print("🌐 Starting server at http://localhost:5001")
    print("   Press Ctrl+C to stop\n")
    
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)


if __name__ == '__main__':
    main()
