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
from .fetchers.emoji_fetcher import EmojiFetcher
from .fetchers.frequency_fetcher import FrequencyFetcher
from .fetchers.dictionary_fetcher import DictionaryFetcher
from .fetchers.translation_fetcher import TranslationFetcher

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

# Generation state
_gen_state = {
    'status': 'idle',
    'current': 0,
    'total': 0,
    'current_word': '',
    'successful': 0,
    'failed': 0,
    'log': [],
    'filename': '',
    'error': '',
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
    
    # Reset state
    _gen_state = {
        'status': 'running',
        'current': 0,
        'total': count,
        'current_word': '',
        'successful': 0,
        'failed': 0,
        'log': [],
        'filename': filename,
        'error': '',
    }
    
    def generate_background():
        global _gen_state
        
        try:
            gen = get_generator()
            gen.reset()
            
            mgr = WordbankManager(str(DATA_DIR / filename))
            
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
                
                # Keep log size manageable
                if len(_gen_state['log']) > 50:
                    _gen_state['log'] = _gen_state['log'][-50:]
                
                time.sleep(0.1)
            
            # Save
            mgr.save()
            _gen_state['status'] = 'complete'
            
        except Exception as e:
            _gen_state['status'] = 'error'
            _gen_state['error'] = str(e)
    
    thread = threading.Thread(target=generate_background)
    thread.start()
    
    return jsonify({'success': True})


@app.route('/api/generate/status')
def api_generate_status():
    """Get generation status."""
    return jsonify(_gen_state)


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
║  Data directory: {str(DATA_DIR):<40} ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    print("🌐 Starting server at http://localhost:5001")
    print("   Press Ctrl+C to stop\n")
    
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)


if __name__ == '__main__':
    main()
