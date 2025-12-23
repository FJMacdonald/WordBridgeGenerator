"""
WordBank Generator - Flask Web Application

Main entry point for the web application.
"""

import os
import json
import time
import threading
from pathlib import Path

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
from .fetchers.dictionary_fetcher import DictionaryFetcher, DataSourceMode
from .fetchers.translation_fetcher import TranslationFetcher
from .fetchers.idiom_fetcher import IdiomFetcher
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

# Generation state
_gen_state = {
    'status': 'idle',
    'current': 0,
    'total': 0,
    'current_word': '',
    'successful': 0,
    'failed': 0,
    'skipped_approved': 0,  # Track approved entries that were used
    'log': [],
    'filename': '',
    'error': '',
    'mode': 'wordnik_preferred',
    'quality_mode': 'strict',
    'api_status': {},
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
    return render_template('generate.html', 
                          active_tab='generate',
                          files=files)


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
    mode = data.get('mode', 'wordnik_preferred')
    quality_mode = data.get('quality_mode', 'strict')
    use_master = data.get('use_master_wordbank', True)
    
    # Convert mode string to enum
    mode_map = {
        'wordnik_preferred': DataSourceMode.WORDNIK_PREFERRED,
        'free_dictionary_only': DataSourceMode.FREE_DICTIONARY_ONLY,
        'overnight': DataSourceMode.OVERNIGHT,
    }
    data_mode = mode_map.get(mode, DataSourceMode.WORDNIK_PREFERRED)
    
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
    }
    
    def generate_background():
        global _gen_state, _generator
        
        try:
            # Create new generator with specified settings
            _generator = WordGenerator(
                mode=data_mode,
                quality_mode=quality_mode,
                use_master_wordbank=use_master,
            )
            gen = _generator
            gen.reset()
            
            # Update API status
            _gen_state['api_status'] = gen.get_api_status()
            
            mgr = WordbankManager(str(DATA_DIR / filename))
            master = get_master_wordbank('en') if use_master else None
            
            # Get candidate words
            if custom_words:
                words = custom_words
            else:
                words = gen.get_candidate_words(count * 3)
            
            target = count
            
            for word in words:
                if _gen_state['successful'] >= target:
                    break
                
                _gen_state['current'] += 1
                _gen_state['current_word'] = word
                
                try:
                    # Check if word is in master wordbank
                    word_lower = word.lower().strip()
                    if master and master.is_approved(word_lower):
                        # Use approved entry
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
                        _gen_state['log'].append(f"✓ {entry.emoji} {entry.word} ({entry.partOfSpeech})")
                    else:
                        _gen_state['failed'] += 1
                        _gen_state['log'].append(f"✗ {word} - skipped")
                    
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
            
            # Merge master wordbank entries
            if master and master.count() > 0:
                mgr.data = master.merge_into_wordbank(mgr.data)
            
            # Save
            mgr.save()
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


@app.route('/api/generate/status')
def api_generate_status():
    """Get generation status."""
    return jsonify(_gen_state)


@app.route('/api/generate/set-mode', methods=['POST'])
def api_generate_set_mode():
    """
    Change generation mode during generation.
    
    Request body:
        mode: 'wordnik_preferred', 'free_dictionary_only', or 'overnight'
    """
    global _generator
    
    data = request.json
    mode = data.get('mode', 'wordnik_preferred')
    
    mode_map = {
        'wordnik_preferred': DataSourceMode.WORDNIK_PREFERRED,
        'free_dictionary_only': DataSourceMode.FREE_DICTIONARY_ONLY,
        'overnight': DataSourceMode.OVERNIGHT,
    }
    
    if mode not in mode_map:
        return jsonify({'success': False, 'error': f'Unknown mode: {mode}'})
    
    if _generator:
        _generator.set_mode(mode_map[mode])
    
    _gen_state['mode'] = mode
    
    return jsonify({'success': True, 'mode': mode})


# =============================================================================
# ROUTES - API STATUS
# =============================================================================

@app.route('/api/status')
def api_status():
    """
    Get comprehensive API status.
    
    Returns status for:
    - Wordnik (auth, rate limits)
    - Free Dictionary
    - Datamuse
    
    Plus recommendations for best mode to use.
    """
    tracker = get_api_tracker()
    statuses = tracker.check_all_apis()
    recommendation = tracker.get_recommended_mode()
    
    return jsonify({
        'wordnik': statuses['wordnik'].to_dict(),
        'free_dictionary': statuses['free_dictionary'].to_dict(),
        'datamuse': statuses['datamuse'].to_dict(),
        'recommendation': recommendation,
    })


@app.route('/api/status/wordnik')
def api_status_wordnik():
    """
    Get detailed Wordnik API status.
    
    Returns:
    - Authentication status
    - Rate limit information
    - Recommendations
    """
    tracker = get_api_tracker()
    status = tracker.check_wordnik_auth()
    
    return jsonify({
        'status': status.to_dict(),
        'recommendation': tracker.get_recommended_mode(),
    })


# =============================================================================
# ROUTES - MASTER WORDBANK
# =============================================================================

@app.route('/api/master/status')
def api_master_status():
    """
    Get master wordbank status.
    
    Returns:
    - Entry count
    - List of approved word IDs
    """
    language = request.args.get('language', 'en')
    master = get_master_wordbank(language)
    
    return jsonify({
        'language': language,
        'count': master.count(),
        'approved_ids': list(master.get_all_approved_ids()),
    })


@app.route('/api/master/approve', methods=['POST'])
def api_master_approve():
    """
    Approve an entry and add it to the master wordbank.
    
    Request body:
        file: Source wordbank filename
        entry_id: Entry ID to approve
        approved_by: Curator name (optional)
        notes: Notes about the entry (optional)
        protected_fields: List of fields to protect (optional)
    """
    data = request.json
    filename = data.get('file')
    entry_id = data.get('entry_id')
    approved_by = data.get('approved_by', 'curator')
    notes = data.get('notes', '')
    protected_fields = data.get('protected_fields')
    language = data.get('language', 'en')
    
    if not filename or not entry_id:
        return jsonify({'success': False, 'error': 'Missing file or entry_id'})
    
    # Load entry from wordbank
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return jsonify({'success': False, 'error': 'File not found'})
    
    mgr = WordbankManager(str(filepath))
    entry = mgr.get_entry(entry_id)
    
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found'})
    
    # Add to master wordbank
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
            'message': f"Entry '{entry.get('word')}' approved and added to master wordbank.",
            'master_count': master.count(),
        })
    else:
        return jsonify({'success': False, 'error': 'Failed to save to master wordbank'})


@app.route('/api/master/remove', methods=['POST'])
def api_master_remove():
    """
    Remove an entry from the master wordbank.
    
    Request body:
        entry_id: Entry ID to remove
        language: Language code (optional, default 'en')
    """
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
            'message': f"Entry '{entry_id}' removed from master wordbank.",
            'master_count': master.count(),
        })
    else:
        return jsonify({'success': False, 'error': 'Entry not found in master wordbank'})


@app.route('/api/master/list')
def api_master_list():
    """
    List all entries in the master wordbank with metadata.
    
    Query parameters:
        language: Language code (default 'en')
    """
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
    """
    Import entries from a wordbank into the master wordbank.
    
    Request body:
        file: Source wordbank filename
        entry_ids: List of entry IDs to import (optional, imports all if not specified)
        approved_by: Curator name (optional)
        language: Language code (optional, default 'en')
    """
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
    """
    Get a specific entry from the master wordbank.
    
    Query parameters:
        language: Language code (default 'en')
    """
    language = request.args.get('language', 'en')
    master = get_master_wordbank(language)
    
    entry_data = master.get_entry_with_metadata(entry_id)
    
    if entry_data:
        return jsonify({
            'success': True,
            'entry': entry_data,
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Entry not found in master wordbank',
        })


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
        # Show file selection
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
    
    # Ensure entry has all required fields
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
        # Show setup page
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
    
    # Load reference entry
    if entry and ref_file:
        ref_path = DATA_DIR / ref_file
        if ref_path.exists():
            ref_mgr = WordbankManager(str(ref_path))
            ref_entry = ref_mgr.get_entry(entry.get('id', ''))
    
    # Ensure entry has all required fields
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
        # Load source
        with open(source_path, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
        
        # Initialize translation fetcher if needed
        translator = get_translation_fetcher() if auto_translate else None
        
        # Create translation structure
        trans_data = {
            'version': '2.0',
            'language': language,
            'sourceLanguage': source_data.get('language', 'en'),
            'generatedAt': '',
            'generationMethod': 'translation',
            'totalEntries': len(source_data.get('words', [])),
            'words': [],
        }
        
        # Copy entries with translations
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
            
            # Auto-translate if enabled
            if translator:
                # Translate word
                trans_word = translator.translate(entry.get('word', ''), 'en', language)
                if trans_word:
                    trans_entry['word'] = trans_word
                
                # Translate definition
                trans_def = translator.translate(entry.get('definition', ''), 'en', language)
                if trans_def:
                    trans_entry['definition'] = trans_def
                
                # Translate sentences
                for sentence in entry.get('sentences', [])[:2]:
                    trans_sent = translator.translate(sentence, 'en', language)
                    if trans_sent:
                        trans_entry['sentences'].append(trans_sent)
            
            trans_data['words'].append(trans_entry)
        
        # Save
        from datetime import datetime
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


@app.route('/api/distractors', methods=['POST'])
def api_distractors():
    """Generate distractors for a word."""
    data = request.json
    word = data.get('word', '')
    pos = data.get('pos', 'noun')
    avoid = set(data.get('avoid', []))
    rhymes = data.get('rhymes', [])
    
    freq = get_frequency_fetcher()
    dict_fetcher = get_dictionary_fetcher()
    detector = get_sound_detector()
    
    dist_gen = DistractorGenerator(freq, dict_fetcher, detector)
    distractors = dist_gen.generate(word, pos, avoid, rhymes)
    
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
    
    # Find and update entry
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
            
            # Determine review status
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
# ROUTES - IDIOM MANAGEMENT
# =============================================================================

@app.route('/api/idioms/search')
def api_idioms_search():
    """
    Search for idioms containing a word.
    
    Query parameters:
        word: Target word to search for
        language: Language code (default 'en')
        use_web: Whether to search web sources (default true)
    
    Returns:
        List of idioms containing the word
    """
    word = request.args.get('word', '')
    language = request.args.get('language', 'en')
    use_web = request.args.get('use_web', 'true').lower() == 'true'
    
    if not word:
        return jsonify({'idioms': [], 'error': 'No word specified'})
    
    idiom_fetcher = get_idiom_fetcher()
    idioms = idiom_fetcher.fetch_idioms(word, language, use_web)
    
    return jsonify({'idioms': idioms, 'word': word, 'language': language})


@app.route('/api/idioms/add', methods=['POST'])
def api_idioms_add():
    """
    Add an idiom to the idiom file for a language.
    
    Request body:
        idiom: The idiom string to add
        language: Language code (default 'en')
    
    Returns:
        Success status
    """
    data = request.json
    idiom = data.get('idiom', '').strip()
    language = data.get('language', 'en')
    
    if not idiom:
        return jsonify({'success': False, 'error': 'No idiom specified'})
    
    idiom_fetcher = get_idiom_fetcher()
    success = idiom_fetcher.add_idiom_to_file(idiom, language)
    
    return jsonify({'success': success})


@app.route('/api/idioms/reload', methods=['POST'])
def api_idioms_reload():
    """
    Reload idiom files after external edits.
    
    Request body:
        language: Language code (default 'en')
    
    Returns:
        Number of idioms loaded
    """
    data = request.json
    language = data.get('language', 'en')
    
    idiom_fetcher = get_idiom_fetcher()
    count = idiom_fetcher.reload_idiom_file(language)
    
    return jsonify({'success': True, 'count': count, 'language': language})


@app.route('/api/idioms/update-entry', methods=['POST'])
def api_idioms_update_entry():
    """
    Update idioms for a specific wordbank entry.
    
    This allows updating idioms independently of other edits,
    supporting parallel workflows where one person edits entries
    while another collects idioms.
    
    Request body:
        file: Wordbank filename
        entry_id: Entry ID to update
        language: Language code for idiom search
        use_web: Whether to search web sources
    
    Returns:
        Updated list of idioms
    """
    data = request.json
    filename = data.get('file')
    entry_id = data.get('entry_id')
    language = data.get('language', 'en')
    use_web = data.get('use_web', True)
    
    if not filename or not entry_id:
        return jsonify({'success': False, 'error': 'Missing file or entry_id'})
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return jsonify({'success': False, 'error': 'File not found'})
    
    mgr = WordbankManager(str(filepath))
    entry = mgr.get_entry(entry_id)
    
    if not entry:
        return jsonify({'success': False, 'error': 'Entry not found'})
    
    word = entry.get('word', '')
    if not word:
        return jsonify({'success': False, 'error': 'Entry has no word'})
    
    # Fetch idioms
    idiom_fetcher = get_idiom_fetcher()
    idioms = idiom_fetcher.fetch_idioms(word, language, use_web)
    
    # Update entry
    entry['phrases'] = idioms
    mgr.save()
    
    return jsonify({
        'success': True, 
        'idioms': idioms, 
        'word': word,
        'count': len(idioms)
    })


@app.route('/api/idioms/batch-update', methods=['POST'])
def api_idioms_batch_update():
    """
    Update idioms for all entries in a wordbank.
    
    This is useful for processing a curated idiom file and
    updating all entries that match.
    
    Request body:
        file: Wordbank filename
        language: Language code
        use_web: Whether to search web sources
    
    Returns:
        Summary of updates
    """
    data = request.json
    filename = data.get('file')
    language = data.get('language', 'en')
    use_web = data.get('use_web', False)  # Default to file-only for batch
    
    if not filename:
        return jsonify({'success': False, 'error': 'No file specified'})
    
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return jsonify({'success': False, 'error': 'File not found'})
    
    mgr = WordbankManager(str(filepath))
    idiom_fetcher = get_idiom_fetcher()
    
    # Reload idiom file to get latest
    idiom_fetcher.reload_idiom_file(language)
    
    updated = 0
    total_idioms = 0
    
    for entry in mgr.data.get('words', []):
        word = entry.get('word', '')
        if not word:
            continue
        
        idioms = idiom_fetcher.fetch_idioms(word, language, use_web)
        
        if idioms:
            entry['phrases'] = idioms
            updated += 1
            total_idioms += len(idioms)
    
    mgr.save()
    
    return jsonify({
        'success': True,
        'entries_updated': updated,
        'total_idioms': total_idioms,
        'total_entries': mgr.count()
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
║  Tabs:                                                   ║
║  • Generate - Create new wordbanks                       ║
║  • Edit - Review and modify entries                      ║
║  • Translate - Create translations                       ║
╠══════════════════════════════════════════════════════════╣
║  Idiom Management:                                       ║
║  • Idioms from files: idioms_{{lang}}.txt                 ║
║  • Web source: idioms.thefreedictionary.com              ║
║  • API: /api/idioms/search, /api/idioms/batch-update     ║
╠══════════════════════════════════════════════════════════╣
║  Data directory: {str(DATA_DIR):<40} ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    print("🌐 Starting server at http://localhost:5001")
    print("   Press Ctrl+C to stop\n")
    
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)


if __name__ == '__main__':
    main()
