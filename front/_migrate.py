"""全站样式 token 迁移脚本（幂等）。跑完即删。

规则见 docs/superpowers/plans/2026-11-18-design-system.md。
只替换 <style> 段里的 CSS 声明值，不碰 template/script。
"""
import io
import re
import sys

RULES = [
    (r'(?<=color: )#8888aa\b', 'var(--text-muted)'),
    (r'(?<=color: )#94a3b8\b', 'var(--text-muted)'),
    (r'(?<=color: )#cbd5e1\b', 'var(--text-body)'),
    (r'(?<=color: )#e2e8f0\b', 'var(--text-body)'),
    (r'(?<=font-size: )0\.8[2-8]rem\b', 'var(--text-sm)'),
    (r'(?<=border-radius: )6px\b', 'var(--radius-xs)'),
    (r'(?<=border-radius: )8px\b', 'var(--radius-sm)'),
    (r'(?<=border-radius: )(9|10|11)px\b', 'var(--radius-md)'),
    (r'(?<=border-radius: )(12|14)px\b', 'var(--radius-lg)'),
    (r'(?<=border-radius: )(16|18|20)px\b', 'var(--radius-xl)'),
]

BATCHES = {
    # 批次 2：大页面
    '2': [
        'src/views/SettingsView.vue',
        'src/views/CharactersView.vue',
        'src/views/MemoryView.vue',
    ],
    # 批次 3：其余页面 + 剩下的组件
    '3': [
        'src/views/HomeView.vue',
        'src/views/NpcGroupChatView.vue',
        'src/views/DigestView.vue',
        'src/views/StoryView.vue',
        'src/views/DesktopWidget.vue',
        'src/views/PoC3DAvatar.vue',
        'src/views/OAuthCallbackView.vue',
        'src/components/VoiceCallModal.vue',
        'src/components/VoiceCallButton.vue',
        'src/components/IncomingCallModal.vue',
        'src/components/DiaryModal.vue',
        'src/components/ActivityInviteCard.vue',
        'src/components/WorldEventPanel.vue',
        'src/App.vue',
    ],
}


def split_style(text):
    m = re.search(r'<style[^>]*>', text)
    if not m:
        return None
    start, end = m.end(), text.rfind('</style>')
    if end < start:
        return None
    return text[:start], text[start:end], text[end:]


def migrate(path):
    text = io.open(path, encoding='utf-8').read()
    parts = split_style(text)
    if parts is None:
        print(f'  跳过（无 style）: {path}')
        return 0
    head, style, tail = parts
    count = 0
    for pattern, repl in RULES:
        style, n = re.subn(pattern, repl, style)
        count += n
    if count:
        io.open(path, 'w', encoding='utf-8', newline='').write(head + style + tail)
    print(f'  {path}: {count} 处')
    return count


if __name__ == '__main__':
    batch = sys.argv[1] if len(sys.argv) > 1 else ''
    files = BATCHES.get(batch, [])
    if not files:
        print('用法: python _migrate.py 2|3')
        sys.exit(1)
    total = sum(migrate(f) for f in files)
    print('总计:', total)
