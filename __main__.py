"""
Entry point for running as a module: python -m WordBridgeGenerator

Usage:
    python -m WordBridgeGenerator                    # Run web app
    python -m WordBridgeGenerator --test-oxford      # Run Oxford 3000 test generation
    python -m WordBridgeGenerator --test-oxford 20   # Test with 20 words
"""

import sys


def main():
    args = sys.argv[1:]
    
    if '--test-oxford' in args:
        # Run Oxford 3000 test generation
        from .generators.oxford_wordbank_generator import OxfordWordbankGenerator
        from .config import DATA_DIR
        
        # Get word count from args if provided
        word_count = 10
        for i, arg in enumerate(args):
            if arg == '--test-oxford' and i + 1 < len(args):
                try:
                    word_count = int(args[i + 1])
                except ValueError:
                    pass
        
        print(f"\n🧪 Running Oxford 3000 Test Generation with {word_count} words\n")
        
        generator = OxfordWordbankGenerator(test_mode=True, test_word_count=word_count)
        output_path = DATA_DIR / "test_wordbank_oxford.json"
        
        entries, issues = generator.generate_wordbank(str(output_path))
        
        print("\n" + "=" * 60)
        print("📊 Test Generation Summary")
        print("=" * 60)
        print(f"Words processed: {word_count}")
        print(f"Entries generated: {len(entries)}")
        print(f"Words skipped (too abstract): {len(issues.words_skipped_too_abstract)}")
        print(f"Words needing emoji review: {len(issues.words_needing_emoji_review)}")
        print(f"Words without emoji/image: {len(issues.words_without_emoji)}")
        print(f"Words without definition: {len(issues.words_without_definition)}")
        print(f"Words without categories: {len(issues.words_without_categories)}")
        print(f"Words with insufficient distractors: {len(issues.words_with_insufficient_distractors)}")
        print(f"API errors: {len(issues.api_errors)}")
        
        # Count difficulty levels
        easy_count = sum(1 for e in entries if e.get('difficulty') == 'easy')
        medium_count = sum(1 for e in entries if e.get('difficulty') == 'medium')
        difficult_count = sum(1 for e in entries if e.get('difficulty') == 'difficult')
        
        print(f"\n📊 Difficulty Breakdown:")
        print(f"  Easy (direct emoji): {easy_count}")
        print(f"  Medium (NounProject): {medium_count}")
        print(f"  Difficult (indirect match): {difficult_count}")
        
        # Show skipped words
        if issues.words_skipped_too_abstract:
            print(f"\n🚫 Skipped (no associations):")
            for item in issues.words_skipped_too_abstract[:5]:
                print(f"  - {item['word']} ({item['pos']})")
            if len(issues.words_skipped_too_abstract) > 5:
                print(f"  ... and {len(issues.words_skipped_too_abstract) - 5} more")
        
        print()
        print(f"Output files:")
        print(f"  - Wordbank: {output_path}")
        print(f"  - API responses: {DATA_DIR / 'test_api_responses.json'}")
        print(f"  - Issues report: {DATA_DIR / 'generation_issues_report.json'}")
        
    elif '--help' in args or '-h' in args:
        print(__doc__)
        
    else:
        # Run web app
        from .app import main as app_main
        app_main()


if __name__ == '__main__':
    main()
