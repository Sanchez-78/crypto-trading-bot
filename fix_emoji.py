import re

with open('src/services/reset_db.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace emojis (both Unicode characters and escape sequences) with plain text
replacements = {
    '📊': '[COUNT]',
    '✅': '[OK]',
    '⚠️': '[WARN]',
    '🔴': '[FAIL]',
    '❌': '[ERROR]',
    '🧹': '[CLEAN]',
}

for emoji, text in replacements.items():
    content = content.replace(emoji, text)

# Also replace Unicode escape sequences
content = re.sub(r'\\U[0-9a-fA-F]{8}', '[*]', content)

with open('src/services/reset_db.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Emoji characters removed from reset_db.py")
