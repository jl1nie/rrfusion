#!/usr/bin/env python3
"""Fix mixed-language queries in documentation.

Replaces JP queries that have English keywords with Japanese-only keywords.
"""

import re
from pathlib import Path

# Patterns to fix (JP queries with English keywords)
FIXES = [
    # Pattern 1: "顔認証 OR face recognition"
    (
        r'\(顔認証 OR face recognition\)',
        '(顔認証 OR 顔識別)',
    ),
    # Pattern 2: "プライバシー保護 OR privacy"
    (
        r'\(プライバシー保護 OR privacy\)',
        '(プライバシー保護 OR 個人情報保護)',
    ),
    # Pattern 3: Full example from archive
    (
        r'\(顔認証 OR face recognition\) AND \(プライバシー保護 OR privacy\)',
        '(顔認証 OR 顔識別) AND (プライバシー保護 OR 個人情報保護)',
    ),
]

def fix_file(file_path: Path) -> bool:
    """Fix mixed-language queries in a single file.

    Returns True if file was modified.
    """
    content = file_path.read_text(encoding='utf-8')
    original_content = content

    for pattern, replacement in FIXES:
        content = re.sub(pattern, replacement, content)

    if content != original_content:
        file_path.write_text(content, encoding='utf-8')
        return True
    return False


def main():
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / 'docs'

    modified_files = []

    # Process all markdown files in docs/
    for md_file in docs_dir.rglob('*.md'):
        if fix_file(md_file):
            modified_files.append(md_file.relative_to(repo_root))

    if modified_files:
        print(f"✅ Fixed {len(modified_files)} files:")
        for f in modified_files:
            print(f"   - {f}")
    else:
        print("No files needed fixing.")


if __name__ == '__main__':
    main()
