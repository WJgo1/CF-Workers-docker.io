/**
 * 完整的端到端运行时测试 —— 用 jsdom 模拟浏览器
 */
import { JSDOM } from 'jsdom';
import fs from 'fs';
import vm from 'vm';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const baseDir = path.resolve(__dirname, '..');

let passed = 0;
let failed = 0;
const errors = [];

function check(label, condition, detail = '') {
    if (condition) {
        console.log(`  ✅ ${label}`);
        passed++;
    } else {
        console.log(`  ❌ ${label}${detail ? ' — ' + detail : ''}`);
        failed++;
    }
}

async function runTest() {
    console.log('');
    console.log('╔═══════════════════════════════════════════╗');
    console.log('║  Markdown 阅读器 完整运行时验证             ║');
    console.log('╚═══════════════════════════════════════════╝');
    console.log('');

    // ============ 设置 jsdom ============
    console.log('📦 初始化 jsdom 环境...');

    const html = fs.readFileSync(path.join(baseDir, 'index.html'), 'utf8');
    const appCode = fs.readFileSync(path.join(baseDir, 'js/app.js'), 'utf8');

    const dom = new JSDOM(html, {
        pretendToBeVisual: true,
        url: 'file://' + baseDir + '/index.html',
        runScripts: 'outside-only',
    });
    const w = dom.window;

    // 关键修复：jsdom 里 globalThis !== window，导致 UMD 库找不到挂载对象
    Object.defineProperty(w, 'globalThis', {
        value: w, writable: false, configurable: true, enumerable: false,
    });

    // 先 mock FileReader 和 FileList（在 vm context 之前）
    const storage = {};
    const localStorage = {
        getItem: (k) => storage[k] ?? null,
        setItem: (k, v) => { storage[k] = String(v); },
        removeItem: (k) => { delete storage[k]; },
        clear: () => { for (const k in storage) delete storage[k]; },
    };

    // 模拟 FileReader — 关键：result 不能直接赋值（jsdom 是只读 getter），
    // 需要用 Object.defineProperty 在实例上覆盖
    let testMd = '# 测试';
    class MockFileReader extends w.FileReader {
        readAsText() {
            setTimeout(() => {
                Object.defineProperty(this, 'result', { value: testMd, writable: true, configurable: true });
                Object.defineProperty(this, 'readyState', { value: 2, writable: true, configurable: true });
                if (this.onload) this.onload({ target: this });
                if (this.onloadend) this.onloadend({ target: this });
            }, 0);
        }
    }
    w.FileReader = MockFileReader;

    // 模拟 DataTransfer 和 FileList
    const fakeFile = { name: 'test.md', text: () => Promise.resolve(testMd) };
    const fakeFileList = Object.defineProperty([fakeFile], Symbol.toStringTag, { value: 'FileList' });
    w.DataTransfer = class DataTransfer {
        constructor() { this.files = fakeFileList; }
    };

    // 收集运行时错误
    w.addEventListener('error', (e) => {
        errors.push(`runtime: ${e.message}`);
    });

    // ============ 先在纯 context 里加载库，再挂载 ============
    console.log('📦 注入库...');
    const libCtx = vm.createContext({ console });
    libCtx.window = libCtx;
    libCtx.globalThis = libCtx;
    libCtx.self = libCtx;
    vm.runInContext(fs.readFileSync(path.join(baseDir, 'libs/marked.min.js'), 'utf8'), libCtx);
    vm.runInContext(fs.readFileSync(path.join(baseDir, 'libs/highlight.min.js'), 'utf8'), libCtx);

    // 把库复制到 jsdom window（这样在 w.document.querySelector 上就能用了）
    w.marked = libCtx.marked;
    w.hljs = libCtx.hljs;

    // ============ 创建 app.js 运行用的 context ============
    const ctx = vm.createContext({});
    ctx.document = w.document;
    ctx.window = ctx;
    ctx.self = ctx;
    ctx.globalThis = ctx;
    ctx.localStorage = localStorage;
    ctx.FileReader = MockFileReader;
    ctx.Blob = w.Blob;
    ctx.URL = w.URL;
    ctx.addEventListener = w.addEventListener.bind(w);
    ctx.removeEventListener = w.removeEventListener?.bind(w);
    ctx.console = console;
    ctx.setTimeout = setTimeout;
    ctx.clearTimeout = clearTimeout;
    ctx.Event = w.Event;
    ctx.CustomEvent = w.CustomEvent;
    ctx.fetch = w.fetch?.bind(w);
    ctx.HTMLElement = w.HTMLElement;
    ctx.HTMLInputElement = w.HTMLInputElement;
    ctx.DOMTokenList = w.DOMTokenList;
    ctx.NodeList = w.NodeList;
    ctx.Element = w.Element;
    ctx.Node = w.Node;
    ctx.Text = w.Text;
    ctx.DocumentFragment = w.DocumentFragment;
    ctx.CSSStyleDeclaration = w.CSSStyleDeclaration;
    ctx.HTMLCollection = w.HTMLCollection;
    ctx.DataTransfer = class {};
    ctx.location = w.location;
    ctx.history = w.history;
    ctx.navigator = w.navigator;
    // 关键：把库也挂到这里
    ctx.marked = libCtx.marked;
    ctx.hljs = libCtx.hljs;

    // ============ 测试 1: 库加载 ============
    console.log('\n🔍 [1] 库加载验证');
    check('marked 全局对象', typeof w.marked === 'object');
    check('marked.parse', typeof w.marked?.parse === 'function');
    check('marked.setOptions', typeof w.marked?.setOptions === 'function');
    check('marked.use', typeof w.marked?.use === 'function');
    check('hljs 全局对象', typeof w.hljs === 'object');
    check('hljs.highlightElement', typeof w.hljs?.highlightElement === 'function');
    check('hljs 语言数量 >= 30', w.hljs?.listLanguages?.().length >= 30);

    // marked 实际解析
    const parseResult = w.marked.parse('# Hello **World**');
    check('marked.parse 输出 <h1>', parseResult.includes('<h1>'));
    check('marked.parse 输出 <strong>', parseResult.includes('<strong>'));

    // ============ 测试 2: 注入 app.js 并触发初始化 ============
    console.log('\n🔧 [2] 注入 app.js 并触发 DOMContentLoaded');

    // 运行 app.js
    vm.runInContext(appCode, ctx);

    // 触发 DOMContentLoaded（app.js 的 init() 在 document 上监听这个事件）
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));

    // ============ 测试 3: 初始 DOM 渲染 ============
    console.log('\n🔍 [3] 初始 DOM 状态（欢迎屏幕）');

    const doc = w.document;

    check('welcome-screen h1 存在', !!doc.querySelector('.welcome-screen h1'),
          doc.querySelector('.welcome-screen h1')?.textContent?.trim());
    check('h1 内容正确', doc.querySelector('.welcome-screen h1')?.textContent?.includes('Markdown 阅读器'));

    check('btn-open-file 存在', !!doc.getElementById('btn-open-file'));
    check('btn-theme 存在', !!doc.getElementById('btn-theme'));
    check('btn-search 存在', !!doc.getElementById('btn-search'));
    check('btn-export 存在', !!doc.getElementById('btn-export'));

    check('左侧边栏 #sidebar 存在', !!doc.getElementById('sidebar'));
    check('右侧 TOC #toc-panel 存在', !!doc.getElementById('toc-panel'));
    check('底部状态栏 #status-theme 存在', !!doc.getElementById('status-theme'));

    // ============ 测试 4: 主题和字体初始化 ============
    console.log('\n🔍 [4] 主题/字体初始化');
    check('html[data-theme] 属性设置', doc.documentElement.getAttribute('data-theme') !== null);
    check('状态栏显示"主题"', doc.getElementById('status-theme')?.textContent?.includes('主题'));

    // ============ 测试 5: 模拟打开文件并渲染 ============
    console.log('\n📝 [5] 模拟打开 Markdown 文件并渲染');

    testMd = `# 项目标题

## 功能列表

这是 **粗体**，这是 *斜体*，这是 \`inline code\`。

> 引用块测试

### 代码示例

\`\`\`javascript
// JavaScript
function greet(name) {
    const msg = "Hello, " + name;
    console.log(msg);
}
greet("World");
\`\`\`

\`\`\`python
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
\`\`\`

### 表格

| 项目 | 状态 |
|------|------|
| 功能 A | ✅ 完成 |
| 功能 B | ⏳ 进行中 |

### 任务列表

- [x] 项目设计
- [x] 编码实现
- [ ] 文档编写
`;

    // 触发 file input change
    const fileInput = doc.getElementById('file-input');
    // 绕过 jsdom IDL 限制，直接用 defineProperty 设置 files
    Object.defineProperty(fileInput, 'files', {
        value: fakeFileList, configurable: true,
    });
    fileInput.dispatchEvent(new w.Event('change'));

    await new Promise(r => setTimeout(r, 100));

    // 检查渲染
    const body = doc.getElementById('markdown-body')?.innerHTML || '';
    check('渲染了 <h1>', body.includes('<h1'));
    check('渲染了 <h2>', body.includes('<h2'));
    check('渲染了 <blockquote>', body.includes('<blockquote'));
    check('渲染了 <pre> 代码块', body.includes('<pre'));
    check('渲染了 <table>', body.includes('<table'));

    // 检查 hljs 高亮
    check('hljs 代码高亮应用 (hljs- 前缀)', body.includes('hljs-') || body.includes('hljs class'));

    // 检查 TOC 生成
    const toc = doc.getElementById('toc-content')?.innerHTML || '';
    check('TOC 目录项生成', toc.includes('toc-item'));

    // 检查文件标题更新
    const title = doc.getElementById('file-title')?.textContent || '';
    check('文件标题更新为 test.md', title.includes('test.md'));

    // 检查状态更新
    const chars = doc.getElementById('status-chars')?.textContent || '';
    check('状态栏字符数更新', chars.includes('字符'));

    // ============ 测试 6: 主题切换 ============
    console.log('\n🎨 [6] 主题切换');

    // 点击主题按钮
    doc.getElementById('btn-theme')?.click();
    await new Promise(r => setTimeout(r, 30));

    const newTheme = doc.documentElement.getAttribute('data-theme');
    check('点击主题按钮后 data-theme 改变', newTheme === 'dark');
    check('状态栏主题文字更新', doc.getElementById('status-theme')?.textContent?.includes('暗色'));

    // 再切回来
    doc.getElementById('btn-theme')?.click();
    await new Promise(r => setTimeout(r, 30));
    check('再次点击切回亮色', doc.documentElement.getAttribute('data-theme') === 'light');

    // ============ 测试 7: 侧边栏/目录切换 ============
    console.log('\n🔧 [7] 侧边栏/目录切换');

    doc.getElementById('btn-sidebar')?.click();
    await new Promise(r => setTimeout(r, 30));
    check('侧边栏折叠', doc.getElementById('sidebar')?.classList.contains('collapsed'));

    doc.getElementById('btn-sidebar')?.click();
    await new Promise(r => setTimeout(r, 30));
    check('侧边栏展开', !doc.getElementById('sidebar')?.classList.contains('collapsed'));

    // ============ 测试 8: 字体大小 ============
    console.log('\n🔤 [8] 字体大小调节');

    const bodyBefore = doc.getElementById('markdown-body')?.style?.fontSize;
    doc.getElementById('btn-font-increase')?.click();
    const bodyAfter = doc.getElementById('markdown-body')?.style?.fontSize;
    check('增大字体有效果', bodyAfter !== bodyBefore);

    // ============ 测试 9: 运行时错误 ============
    console.log('\n⚠️  [9] 运行时错误检查');
    check('无运行时错误', errors.length === 0, errors.length > 0 ? errors[0] : '');

    // ============ 汇总 ============
    console.log('\n╔═══════════════════════════════════════════╗');
    console.log('║  测试汇总                                  ║');
    console.log('╚═══════════════════════════════════════════╝');
    console.log(`\n  通过: ${passed}`);
    console.log(`  失败: ${failed}`);
    console.log(`  总计: ${passed + failed}`);

    if (errors.length > 0) {
        console.log(`\n  运行时错误 (${errors.length}):`);
        errors.forEach(e => console.log(`    - ${e}`));
    }

    console.log('');
    if (failed === 0 && errors.length === 0) {
        console.log('  🎉 全部测试通过！应用可正常运行！');
        console.log('');
        console.log('  在 Windows 上直接双击 index.html 即可使用。');
    } else {
        console.log(`  ⚠️  有 ${failed} 项检查未通过。`);
    }
    console.log('');

    w.close();
    process.exit(failed === 0 ? 0 : 1);
}

runTest().catch(err => {
    console.error('\n❌ 测试执行异常:', err);
    process.exit(1);
});
