/**
 * Markdown 阅读器 - 主应用
 */

// ========== 全局状态 ==========
const state = {
    currentFile: null,
    currentFileName: '',
    currentContent: '',
    theme: localStorage.getItem('md-reader-theme') || 'light',
    fontSize: parseInt(localStorage.getItem('md-reader-fontsize')) || 16,
    tocVisible: localStorage.getItem('md-reader-toc') !== 'false',
    sidebarVisible: localStorage.getItem('md-reader-sidebar') !== 'false',
    fileTree: [],
    searchResults: [],
    searchIndex: -1,
};

// ========== DOM 元素 ==========
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
    toolbar: $('.toolbar'),
    btnOpenFile: $('#btn-open-file'),
    btnOpenFolder: $('#btn-open-folder'),
    btnSidebar: $('#btn-sidebar'),
    btnToc: $('#btn-toc'),
    btnTheme: $('#btn-theme'),
    btnFontIncrease: $('#btn-font-increase'),
    btnFontDecrease: $('#btn-font-decrease'),
    btnFontReset: $('#btn-font-reset'),
    btnSearch: $('#btn-search'),
    btnExport: $('#btn-export'),
    fileTitle: $('#file-title'),
    fileInput: $('#file-input'),
    folderInput: $('#folder-input'),
    sidebar: $('#sidebar'),
    fileTree: $('#file-tree'),
    fileSearch: $('#file-search'),
    contentArea: $('#content-area'),
    markdownBody: $('#markdown-body'),
    tocPanel: $('#toc-panel'),
    tocContent: $('#toc-content'),
    statusChars: $('#status-chars'),
    statusWords: $('#status-words'),
    statusLines: $('#status-lines'),
    statusTheme: $('#status-theme'),
    searchOverlay: $('#search-overlay'),
    searchField: $('#search-field'),
    searchPrev: $('#search-prev'),
    searchNext: $('#search-next'),
    searchClose: $('#search-close'),
    searchCount: $('#search-count'),
    highlightLight: $('#highlight-light'),
    highlightDark: $('#highlight-dark'),
};

// ========== 初始化 ==========
function init() {
    applyTheme();
    applyFontSize();
    applyLayout();
    setupMarked();
    setupEventListeners();
    createDragOverlay();
    setupKeyboardShortcuts();
    loadLastFile();
}

// ========== Marked 配置 ==========
function setupMarked() {
    marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: true,
        mangle: false,
    });

    // 自定义渲染器，添加锚点和任务列表支持
    const renderer = new marked.Renderer();

    renderer.heading = function ({ tokens, depth }) {
        const text = this.parser.parseInline(tokens);
        const rawText = tokens.map(t => t.raw || t.text || '').join('');
        const id = generateHeadingId(rawText);
        return `<h${depth} id="${id}">${text}<a href="#${id}" class="header-anchor">#</a></h${depth}>`;
    };

    marked.use({ renderer });
}

function generateHeadingId(text) {
    return text.toLowerCase()
        .replace(/[\s]+/g, '-')
        .replace(/[^\w\u4e00-\u9fa5-]/g, '')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '');
}

// ========== 事件监听 ==========
function setupEventListeners() {
    // 文件打开
    els.btnOpenFile.addEventListener('click', () => els.fileInput.click());
    els.btnOpenFolder.addEventListener('click', () => els.folderInput.click());

    els.fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleFileOpen(file);
    });

    els.folderInput.addEventListener('change', (e) => {
        handleFolderOpen(e.target.files);
    });

    // 侧边栏和目录切换
    els.btnSidebar.addEventListener('click', () => {
        state.sidebarVisible = !state.sidebarVisible;
        localStorage.setItem('md-reader-sidebar', state.sidebarVisible);
        applyLayout();
    });

    els.btnToc.addEventListener('click', () => {
        state.tocVisible = !state.tocVisible;
        localStorage.setItem('md-reader-toc', state.tocVisible);
        applyLayout();
    });

    // 主题
    els.btnTheme.addEventListener('click', () => {
        state.theme = state.theme === 'light' ? 'dark' : 'light';
        localStorage.setItem('md-reader-theme', state.theme);
        applyTheme();
    });

    // 字体大小
    els.btnFontIncrease.addEventListener('click', () => changeFontSize(2));
    els.btnFontDecrease.addEventListener('click', () => changeFontSize(-2));
    els.btnFontReset.addEventListener('click', () => {
        state.fontSize = 16;
        localStorage.setItem('md-reader-fontsize', state.fontSize);
        applyFontSize();
    });

    // 搜索
    els.btnSearch.addEventListener('click', () => toggleSearch(true));
    els.searchClose.addEventListener('click', () => toggleSearch(false));
    els.searchField.addEventListener('input', () => performSearch());
    els.searchPrev.addEventListener('click', () => navigateSearch(-1));
    els.searchNext.addEventListener('click', () => navigateSearch(1));

    // 导出
    els.btnExport.addEventListener('click', exportHTML);

    // 文件树搜索
    els.fileSearch.addEventListener('input', (e) => filterFileTree(e.target.value));

    // 拖拽
    document.addEventListener('dragover', (e) => {
        e.preventDefault();
        showDragOverlay(true);
    });

    document.addEventListener('dragleave', (e) => {
        if (e.target === document.documentElement) showDragOverlay(false);
    });

    document.addEventListener('drop', (e) => {
        e.preventDefault();
        showDragOverlay(false);
        const items = e.dataTransfer.items;
        if (items && items.length > 0) {
            const entry = items[0].webkitGetAsEntry();
            if (entry) {
                if (entry.isFile) {
                    entry.file(handleFileOpen);
                } else if (entry.isDirectory) {
                    handleDirectoryEntry(entry);
                }
            }
        } else {
            const file = e.dataTransfer.files[0];
            if (file) handleFileOpen(file);
        }
    });

    // 点击锚点
    els.markdownBody.addEventListener('click', (e) => {
        const anchor = e.target.closest('a.header-anchor');
        if (anchor) {
            e.preventDefault();
            const id = anchor.getAttribute('href').slice(1);
            const el = document.getElementById(id);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });

    // 滚动高亮当前目录项
    els.contentArea.addEventListener('scroll', updateTocActive);
}

// ========== 键盘快捷键 ==========
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + O - 打开文件
        if ((e.ctrlKey || e.metaKey) && e.key === 'o') {
            e.preventDefault();
            els.fileInput.click();
        }
        // Ctrl/Cmd + B - 侧边栏
        else if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            els.btnSidebar.click();
        }
        // Ctrl/Cmd + T - 主题
        else if ((e.ctrlKey || e.metaKey) && e.key === 't') {
            e.preventDefault();
            els.btnTheme.click();
        }
        // Ctrl/Cmd + + - 放大
        else if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
            e.preventDefault();
            changeFontSize(2);
        }
        // Ctrl/Cmd + - - 缩小
        else if ((e.ctrlKey || e.metaKey) && e.key === '-') {
            e.preventDefault();
            changeFontSize(-2);
        }
        // Ctrl/Cmd + 0 - 重置
        else if ((e.ctrlKey || e.metaKey) && e.key === '0') {
            e.preventDefault();
            state.fontSize = 16;
            localStorage.setItem('md-reader-fontsize', state.fontSize);
            applyFontSize();
        }
        // Ctrl/Cmd + F - 搜索
        else if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            toggleSearch(true);
        }
        // Escape - 关闭搜索
        else if (e.key === 'Escape') {
            if (!els.searchOverlay.hidden) {
                toggleSearch(false);
            }
        }
        // F3 / Ctrl+G - 下一个搜索
        else if (e.key === 'F3' || ((e.ctrlKey || e.metaKey) && e.key === 'g' && !e.shiftKey)) {
            e.preventDefault();
            if (!els.searchOverlay.hidden) navigateSearch(1);
            else toggleSearch(true);
        }
        // Shift + F3 / Ctrl + Shift + G - 上一个搜索
        else if (e.key === 'F3' || ((e.ctrlKey || e.metaKey) && e.key === 'g' && e.shiftKey)) {
            e.preventDefault();
            if (!els.searchOverlay.hidden) navigateSearch(-1);
            else toggleSearch(true);
        }
    });
}

// ========== 主题 ==========
function applyTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
    els.statusTheme.textContent = `主题：${state.theme === 'light' ? '亮色' : '暗色'}`;

    // 切换 highlight.js 样式
    if (state.theme === 'light') {
        els.highlightLight.disabled = false;
        els.highlightDark.disabled = true;
    } else {
        els.highlightLight.disabled = true;
        els.highlightDark.disabled = false;
    }
}

// ========== 字体 ==========
function applyFontSize() {
    els.markdownBody.style.fontSize = state.fontSize + 'px';
}

function changeFontSize(delta) {
    state.fontSize = Math.max(12, Math.min(28, state.fontSize + delta));
    localStorage.setItem('md-reader-fontsize', state.fontSize);
    applyFontSize();
}

// ========== 布局 ==========
function applyLayout() {
    els.sidebar.classList.toggle('collapsed', !state.sidebarVisible);
    els.tocPanel.classList.toggle('collapsed', !state.tocVisible);
}

// ========== 文件处理 ==========
function handleFileOpen(file) {
    if (!file) return;

    const validExts = ['.md', '.markdown', '.mdown', '.mkd', '.txt'];
    const name = file.name.toLowerCase();
    const isValid = validExts.some(ext => name.endsWith(ext));

    if (!isValid) {
        // 仍然允许打开，只是提示
        console.warn('可能不是 Markdown 文件:', file.name);
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        state.currentFile = file;
        state.currentFileName = file.name;
        state.currentContent = e.target.result;
        renderMarkdown(state.currentContent);
        els.fileTitle.textContent = state.currentFileName;
        updateStatus(state.currentContent);
        saveLastFile(file.name);
    };
    reader.readAsText(file, detectEncoding(file));
}

function detectEncoding(file) {
    // 默认使用 UTF-8，对于中文环境可以尝试 GBK
    return 'utf-8';
}

function handleFolderOpen(files) {
    const mdFiles = [];
    const folderStructure = {};

    Array.from(files).forEach(file => {
        if (isMarkdownFile(file.name)) {
            mdFiles.push(file);

            // 构建目录结构
            const path = file.webkitRelativePath || file.name;
            const parts = path.split('/');
            let current = folderStructure;
            parts.forEach((part, i) => {
                if (i === parts.length - 1) {
                    if (!current.files) current.files = [];
                    current.files.push({ name: part, file, path });
                } else {
                    if (!current.folders) current.folders = {};
                    if (!current.folders[part]) current.folders[part] = {};
                    current = current.folders[part];
                }
            });
        }
    });

    state.fileTree = mdFiles;
    renderFileTree(folderStructure);

    // 自动打开第一个文件
    if (mdFiles.length > 0) {
        handleFileOpen(mdFiles[0]);
    }
}

function handleDirectoryEntry(entry) {
    const files = [];
    const readEntry = (entry, path = '') => {
        return new Promise((resolve) => {
            if (entry.isFile) {
                entry.file(file => {
                    const fullPath = path + entry.name;
                    if (isMarkdownFile(entry.name)) {
                        file.webkitRelativePath = fullPath;
                        files.push(file);
                    }
                    resolve();
                });
            } else if (entry.isDirectory) {
                const reader = entry.createReader();
                const promises = [];
                const readBatch = () => {
                    reader.readEntries(entries => {
                        if (entries.length === 0) {
                            resolve(Promise.all(promises));
                        } else {
                            entries.forEach(e => {
                                promises.push(readEntry(e, path + entry.name + '/'));
                            });
                            readBatch();
                        }
                    });
                };
                readBatch();
            } else {
                resolve();
            }
        });
    };

    readEntry(entry).then(() => {
        if (files.length > 0) {
            handleFolderOpen(files);
        }
    });
}

function isMarkdownFile(name) {
    const lower = name.toLowerCase();
    return lower.endsWith('.md') || lower.endsWith('.markdown') ||
           lower.endsWith('.mdown') || lower.endsWith('.mkd') || lower.endsWith('.txt');
}

// ========== 文件树渲染 ==========
function renderFileTree(structure, container = null, depth = 0) {
    if (!container) {
        els.fileTree.innerHTML = '';
        container = els.fileTree;
    }

    // 清空空提示
    const emptyHint = container.querySelector('.empty-hint');
    if (emptyHint) emptyHint.remove();

    // 渲染文件夹
    if (structure.folders) {
        Object.entries(structure.folders).sort(([a], [b]) => a.localeCompare(b)).forEach(([name, folder]) => {
            const folderEl = document.createElement('div');
            folderEl.className = 'folder-item';

            const header = document.createElement('div');
            header.className = 'file-item folder';
            header.innerHTML = `<span class="icon">📁</span><span class="name">${escapeHtml(name)}</span>`;
            header.addEventListener('click', () => {
                folderEl.classList.toggle('open');
            });

            const children = document.createElement('div');
            children.className = 'folder-children';

            folderEl.appendChild(header);
            folderEl.appendChild(children);
            container.appendChild(folderEl);

            // 递归渲染子文件夹和文件
            renderFileTree(folder, children, depth + 1);
        });
    }

    // 渲染文件
    if (structure.files) {
        structure.files.sort((a, b) => a.name.localeCompare(b.name)).forEach(({ name, file, path }) => {
            const fileEl = document.createElement('div');
            fileEl.className = 'file-item';
            fileEl.dataset.path = path;
            fileEl.innerHTML = `<span class="icon">📄</span><span class="name">${escapeHtml(name)}</span>`;
            fileEl.addEventListener('click', () => {
                handleFileOpen(file);
                // 高亮当前文件
                $$('.file-item').forEach(el => el.classList.remove('active'));
                fileEl.classList.add('active');
            });
            container.appendChild(fileEl);
        });
    }
}

function filterFileTree(query) {
    const items = els.fileTree.querySelectorAll('.file-item');
    items.forEach(item => {
        const name = item.querySelector('.name').textContent.toLowerCase();
        const match = name.includes(query.toLowerCase());
        item.style.display = match ? '' : 'none';

        // 如果隐藏，也隐藏父文件夹中只有这个文件的情况
        if (item.parentElement.classList.contains('folder-children')) {
            const folderHeader = item.parentElement.previousElementSibling;
            const hasVisible = Array.from(item.parentElement.querySelectorAll('.file-item'))
                .some(el => el.style.display !== 'none');
            folderHeader.style.display = hasVisible ? '' : 'none';
        }
    });
}

// ========== Markdown 渲染 ==========
function renderMarkdown(content) {
    try {
        let html = marked.parse(content);

        // 代码高亮
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;

        tempDiv.querySelectorAll('pre code').forEach(block => {
            if (window.hljs) {
                try {
                    hljs.highlightElement(block);
                } catch (e) {
                    console.warn('代码高亮失败:', e);
                }
            }
        });

        // 任务列表处理
        tempDiv.querySelectorAll('li input[type="checkbox"]').forEach(cb => {
            // 在 GFM 模式下 marked 会自动处理，这里做额外处理
        });

        els.markdownBody.innerHTML = tempDiv.innerHTML;
        generateToc(content);

        // 滚动到上次位置
        restoreScrollPosition();
    } catch (e) {
        console.error('Markdown 渲染失败:', e);
        els.markdownBody.innerHTML = `<p style="color: red;">渲染失败: ${e.message}</p><pre>${escapeHtml(content)}</pre>`;
    }
}

// ========== 目录生成 ==========
function generateToc(content) {
    els.tocContent.innerHTML = '';

    // 从渲染后的DOM中提取标题
    const headings = els.markdownBody.querySelectorAll('h1, h2, h3, h4, h5, h6');

    if (headings.length === 0) {
        els.tocContent.innerHTML = '<div style="padding: 12px 16px; color: var(--text-muted); font-size: 12px;">暂无目录</div>';
        return;
    }

    headings.forEach((heading, index) => {
        const level = parseInt(heading.tagName.charAt(1));
        const id = heading.id || `heading-${index}`;
        if (!heading.id) heading.id = id;

        const tocItem = document.createElement('a');
        tocItem.href = `#${id}`;
        tocItem.className = `toc-item level-${level}`;
        tocItem.textContent = heading.textContent.replace(/^#\s*$/, '').trim();
        tocItem.dataset.target = id;

        tocItem.addEventListener('click', (e) => {
            e.preventDefault();
            const target = document.getElementById(id);
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });

        els.tocContent.appendChild(tocItem);
    });
}

function updateTocActive() {
    const headings = els.markdownBody.querySelectorAll('h1, h2, h3, h4, h5, h6');
    const tocItems = els.tocContent.querySelectorAll('.toc-item');

    const scrollTop = els.contentArea.scrollTop;
    const offset = 100;

    let currentId = '';
    headings.forEach(heading => {
        if (heading.offsetTop - offset <= scrollTop) {
            currentId = heading.id;
        }
    });

    tocItems.forEach(item => {
        item.classList.toggle('active', item.dataset.target === currentId);
    });
}

// ========== 状态栏 ==========
function updateStatus(content) {
    const chars = content.length;
    // 简单的词统计（中文按字符，英文按空格分割）
    const chineseChars = (content.match(/[\u4e00-\u9fa5]/g) || []).length;
    const englishWords = (content.match(/[a-zA-Z]+/g) || []).length;
    const words = chineseChars + englishWords;
    const lines = content.split('\n').length;

    els.statusChars.textContent = `${chars} 字符`;
    els.statusWords.textContent = `${words} 词`;
    els.statusLines.textContent = `${lines} 行`;
}

// ========== 搜索 ==========
function toggleSearch(show) {
    els.searchOverlay.hidden = !show;
    if (show) {
        els.searchField.focus();
        els.searchField.select();
    } else {
        clearSearch();
    }
}

function performSearch() {
    const query = els.searchField.value.trim();
    clearSearch();

    if (!query) {
        els.searchCount.textContent = '';
        return;
    }

    const content = els.markdownBody;
    const textNodes = getTextNodes(content);
    const regex = new RegExp(escapeRegex(query), 'gi');
    let matchIndex = 0;

    textNodes.forEach(node => {
        const matches = node.textContent.match(regex);
        if (matches) {
            const parent = node.parentNode;
            const fragment = document.createDocumentFragment();
            let lastIndex = 0;
            let nodeMatches = [];

            matches.forEach(match => {
                const idx = node.textContent.toLowerCase().indexOf(match.toLowerCase(), lastIndex);
                if (idx !== -1) {
                    nodeMatches.push({ start: idx, end: idx + match.length });
                    lastIndex = idx + match.length;
                }
            });

            if (nodeMatches.length > 0) {
                nodeMatches.forEach((m, i) => {
                    fragment.appendChild(document.createTextNode(node.textContent.slice(lastIndex, m.start)));
                    const span = document.createElement('span');
                    span.className = 'search-highlight';
                    span.dataset.index = matchIndex;
                    span.textContent = node.textContent.slice(m.start, m.end);
                    fragment.appendChild(span);
                    matchIndex++;
                    lastIndex = m.end;
                });
                fragment.appendChild(document.createTextNode(node.textContent.slice(lastIndex)));
                parent.replaceChild(fragment, node);
            }
        }
    });

    state.searchResults = Array.from(document.querySelectorAll('.search-highlight'));
    state.searchIndex = state.searchResults.length > 0 ? 0 : -1;

    updateSearchCount();
    highlightCurrentSearch();
}

function clearSearch() {
    els.markdownBody.querySelectorAll('.search-highlight').forEach(span => {
        const text = document.createTextNode(span.textContent);
        span.parentNode.replaceChild(text, span);
    });
    // 合并相邻文本节点
    els.markdownBody.normalize();
    state.searchResults = [];
    state.searchIndex = -1;
}

function navigateSearch(direction) {
    if (state.searchResults.length === 0) return;

    state.searchIndex += direction;
    if (state.searchIndex < 0) state.searchIndex = state.searchResults.length - 1;
    if (state.searchIndex >= state.searchResults.length) state.searchIndex = 0;

    updateSearchCount();
    highlightCurrentSearch();
}

function updateSearchCount() {
    if (state.searchResults.length > 0) {
        els.searchCount.textContent = `${state.searchIndex + 1} / ${state.searchResults.length}`;
    } else if (els.searchField.value.trim()) {
        els.searchCount.textContent = '无匹配';
    } else {
        els.searchCount.textContent = '';
    }
}

function highlightCurrentSearch() {
    state.searchResults.forEach((el, i) => {
        el.classList.toggle('active', i === state.searchIndex);
    });
    if (state.searchIndex >= 0 && state.searchResults[state.searchIndex]) {
        state.searchResults[state.searchIndex].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function getTextNodes(element) {
    const nodes = [];
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => {
            if (node.textContent.trim() === '') return NodeFilter.FILTER_REJECT;
            if (node.parentNode.closest('pre')) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        }
    });

    let node;
    while ((node = walker.nextNode())) {
        nodes.push(node);
    }
    return nodes;
}

// ========== 导出 ==========
function exportHTML() {
    if (!state.currentContent) {
        alert('请先打开一个 Markdown 文件');
        return;
    }

    const htmlContent = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${state.currentFileName}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 40px 20px; line-height: 1.6; color: #24292f; }
        h1, h2 { border-bottom: 1px solid #d0d7de; padding-bottom: 0.3em; }
        code { background: #f6f8fa; padding: 0.2em 0.4em; border-radius: 6px; font-size: 85%; font-family: Consolas, monospace; }
        pre { background: #f6f8fa; padding: 16px; border-radius: 6px; overflow: auto; }
        pre code { background: none; padding: 0; }
        blockquote { border-left: 4px solid #d0d7de; padding-left: 1em; color: #656d76; margin: 0; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #d0d7de; padding: 6px 13px; }
        img { max-width: 100%; }
        a { color: #0969da; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
${marked.parse(state.currentContent)}
</body>
</html>`;

    const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = state.currentFileName.replace(/\.(md|markdown|mdown|mkd)$/i, '') + '.html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ========== 拖拽遮罩 ==========
function createDragOverlay() {
    const overlay = document.createElement('div');
    overlay.className = 'drag-overlay hidden';
    overlay.innerHTML = '<div class="drag-overlay-content">📂<p>松开以打开文件</p></div>';
    document.body.appendChild(overlay);
    window._dragOverlay = overlay;
}

function showDragOverlay(show) {
    if (window._dragOverlay) {
        window._dragOverlay.classList.toggle('hidden', !show);
    }
}

// ========== 工具函数 ==========
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeRegex(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ========== 本地存储 ==========
function saveLastFile(filename) {
    // 由于浏览器安全限制，无法保存实际文件路径
    localStorage.setItem('md-reader-last-file', filename);
    localStorage.setItem('md-reader-scroll-' + filename, els.contentArea.scrollTop);
}

function loadLastFile() {
    // 只能恢复文件名，无法恢复实际内容
    const lastFile = localStorage.getItem('md-reader-last-file');
    if (lastFile) {
        console.log('上次打开的文件:', lastFile, '（浏览器安全限制，无法自动恢复内容）');
    }
}

function restoreScrollPosition() {
    const saved = localStorage.getItem('md-reader-scroll-' + state.currentFileName);
    if (saved) {
        setTimeout(() => {
            els.contentArea.scrollTop = parseInt(saved);
        }, 100);
    }
}

// ========== 启动 ==========
document.addEventListener('DOMContentLoaded', init);
