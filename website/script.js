const header = document.querySelector('.site-header');
const navToggle = document.querySelector('.nav-toggle');
const navLinks = document.querySelector('.nav-links');
const workspace = document.querySelector('.workspace-section');
const appScreen = document.querySelector('#app-screen');
const heroScreen = document.querySelector('#hero-screen');
const screenButtons = [...document.querySelectorAll('[data-screen]')];
const languageButtons = [...document.querySelectorAll('[data-language]')];

const screenshots = {
  zh: { light: 'assets/app-light.png', dark: 'assets/app-dark.png' },
  en: { light: 'assets/app-light-en.png', dark: 'assets/app-dark-en.png' }
};
let currentLanguage = 'zh';

const copy = {
  zh: {
    title: 'DO编辑器｜清晰、专注的 Windows PDF 工具',
    description: 'DO编辑器是一款适用于 Windows 10/11 的 PDF 阅读、编辑、OCR、签名与安全工具。',
    texts: {
      '.brand span': 'DO编辑器', '.nav-links > a:nth-child(1)': '界面', '.nav-links > a:nth-child(2)': '功能', '.nav-links > a:nth-child(3)': '体验', '.nav-links > a:nth-child(4)': '下载',
      '.hero-copy > p': '阅读、编辑、批注、OCR、签名与加密，集中在一个清晰、轻巧的桌面工具中。', '.button-copy': '下载 Windows 版', '.link-copy': '查看软件界面', '.hero-meta span:nth-child(2)': '中文 / English',
      '.value-grid > div:nth-child(1) strong': '阅读与编辑', '.value-grid > div:nth-child(1) span': '常用操作集中呈现', '.value-grid > div:nth-child(2) strong': 'OCR 识别', '.value-grid > div:nth-child(2) span': '扫描内容也能搜索复制', '.value-grid > div:nth-child(3) strong': '签名与批注', '.value-grid > div:nth-child(3) span': '审阅和确认更加直接', '.value-grid > div:nth-child(4) span': '密码与文档权限保护',
      '.workspace-intro .eyebrow': '软件界面', '.workspace-intro h2': '一眼清晰，操作自然', '.workspace-intro p': '功能有序排布，内容始终是视觉中心。浅色与深色界面可在下方直接切换查看。',
      '.workspace-meta span:nth-child(1)': '真实软件界面', '.workspace-meta span:nth-child(2)': '专用演示文档', '.workspace-meta span:nth-child(3)': '高 DPI 显示优化',
      '.section-lead .eyebrow': '核心功能', '.section-lead h2': '完整，但不复杂', '.section-lead p': '把高频 PDF 工作整合成三个清晰环节，减少来回切换。',
      '.feature-row:nth-child(1) h3': '阅读与整理', '.feature-row:nth-child(1) > p': '连续滚动、多标签页、适合宽度、缩略图侧栏和页面拖动排序，让长文档始终易于掌控。', '.feature-row:nth-child(2) h3': '编辑与审阅', '.feature-row:nth-child(2) > p': '添加和修改文字、插入图片、快捷复制，并通过高亮、线条、图形、签名与批注完成审阅。', '.feature-row:nth-child(3) h3': '识别与保护', '.feature-row:nth-child(3) > p': '识别当前页或全部扫描页面，并通过密码、权限控制和文字水印保护最终文档。',
      '.workflow-copy .eyebrow': '使用体验', '.workflow-copy > p': '不隐藏关键功能，也不过度堆叠工具。常用操作近在手边，文档区域保持宽阔。', '.workflow-list li:nth-child(1) strong': '打开', '.workflow-list li:nth-child(1) p': '直接读取 PDF 与 Word 文档，多标签并行处理。', '.workflow-list li:nth-child(2) strong': '处理', '.workflow-list li:nth-child(2) p': '编辑、识别、批注和签名均在当前工作区完成。', '.workflow-list li:nth-child(3) strong': '交付', '.workflow-list li:nth-child(3) p': '保存、加密并设置权限，安全输出最终文件。',
      '.download-inner h2': '现在开始，专注处理文档', '.download-inner p': '适用于 Windows 10 / 11，支持中文与 English。', '.download-actions .button': '下载安装包', '.footer-brand strong': 'DO编辑器', '.email-label': '联系邮箱', '.email-separator': '：', '.footer-inner > div:last-child a:last-child': '返回顶部 ↑'
    },
    html: { '#hero-title': 'PDF 阅读与编辑，<br><em>清晰、高效。</em>', '.workflow-copy h2': '从打开到交付，<br>始终保持同一节奏' }
  },
  en: {
    title: 'DO Editor | A Clear, Focused PDF Tool for Windows',
    description: 'DO Editor is a focused PDF reader and editor for Windows 10/11 with OCR, signatures, annotations and document security.',
    texts: {
      '.brand span': 'DO Editor', '.nav-links > a:nth-child(1)': 'Interface', '.nav-links > a:nth-child(2)': 'Features', '.nav-links > a:nth-child(3)': 'Experience', '.nav-links > a:nth-child(4)': 'Download',
      '.hero-copy > p': 'Read, edit, annotate, recognize, sign and protect PDFs in one clear, lightweight desktop workspace.', '.button-copy': 'Download for Windows', '.link-copy': 'View the interface', '.hero-meta span:nth-child(2)': 'Chinese / English',
      '.value-grid > div:nth-child(1) strong': 'Read & edit', '.value-grid > div:nth-child(1) span': 'Everyday tools in one place', '.value-grid > div:nth-child(2) strong': 'OCR', '.value-grid > div:nth-child(2) span': 'Make scans searchable', '.value-grid > div:nth-child(3) strong': 'Sign & annotate', '.value-grid > div:nth-child(3) span': 'Review documents directly', '.value-grid > div:nth-child(4) span': 'Password and permission control',
      '.workspace-intro .eyebrow': 'INTERFACE', '.workspace-intro h2': 'Clear at a glance. Natural to use.', '.workspace-intro p': 'Tools stay organized while your document remains the focus. Switch between the light and dark interface below.',
      '.workspace-meta span:nth-child(1)': 'Real application interface', '.workspace-meta span:nth-child(2)': 'Purpose-built demo document', '.workspace-meta span:nth-child(3)': 'High-DPI optimized',
      '.section-lead .eyebrow': 'CORE FEATURES', '.section-lead h2': 'Complete, without the clutter', '.section-lead p': 'A focused set of tools for the three stages of everyday PDF work.',
      '.feature-row:nth-child(1) h3': 'Read & organize', '.feature-row:nth-child(1) > p': 'Continuous scrolling, tabs, fit-to-width viewing, thumbnails and drag-to-reorder keep long documents manageable.', '.feature-row:nth-child(2) h3': 'Edit & review', '.feature-row:nth-child(2) > p': 'Add or revise text, insert images, copy quickly, and review with highlights, shapes, signatures and annotations.', '.feature-row:nth-child(3) h3': 'Recognize & protect', '.feature-row:nth-child(3) > p': 'Run OCR on one page or an entire scan, then protect the result with passwords, permissions and watermarks.',
      '.workflow-copy .eyebrow': 'EXPERIENCE', '.workflow-copy > p': 'Essential tools stay close without crowding the workspace, leaving more room for the document itself.', '.workflow-list li:nth-child(1) strong': 'Open', '.workflow-list li:nth-child(1) p': 'Open PDF and Word documents directly and work across multiple tabs.', '.workflow-list li:nth-child(2) strong': 'Work', '.workflow-list li:nth-child(2) p': 'Edit, recognize, annotate and sign without leaving the workspace.', '.workflow-list li:nth-child(3) strong': 'Deliver', '.workflow-list li:nth-child(3) p': 'Save, encrypt and control permissions before sharing the final file.',
      '.download-inner h2': 'Stay focused on the document', '.download-inner p': 'Made for Windows 10 / 11 with Chinese and English interfaces.', '.download-actions .button': 'Download installer', '.footer-brand strong': 'DO Editor', '.email-label': 'Email', '.email-separator': ': ', '.footer-inner > div:last-child a:last-child': 'Back to top ↑'
    },
    html: { '#hero-title': 'PDF reading and editing,<br><em>clear and efficient.</em>', '.workflow-copy h2': 'From open to delivery,<br>keep a natural rhythm' }
  }
};

Object.values(screenshots).flatMap(Object.values).forEach(source => {
  const image = new Image();
  image.src = source;
});

const updateHeader = () => header?.classList.toggle('scrolled', window.scrollY > 16);
window.addEventListener('scroll', updateHeader, { passive: true });
updateHeader();

navToggle?.addEventListener('click', () => {
  const open = navLinks?.classList.toggle('open') ?? false;
  navToggle.setAttribute('aria-expanded', String(open));
});

navLinks?.addEventListener('click', event => {
  if (!event.target.closest('a')) return;
  navLinks.classList.remove('open');
  navToggle?.setAttribute('aria-expanded', 'false');
});

const setWorkspaceTheme = mode => {
  if (!screenshots[currentLanguage]?.[mode] || !workspace || !appScreen) return;

  workspace.dataset.theme = mode;
  appScreen.src = screenshots[currentLanguage][mode];
  appScreen.alt = currentLanguage === 'en' ? `DO Editor ${mode} interface` : `DO编辑器${mode === 'dark' ? '深色' : '浅色'}主题界面`;

  screenButtons.forEach(button => {
    const selected = button.dataset.screen === mode;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
};

screenButtons.forEach(button => {
  button.addEventListener('click', () => setWorkspaceTheme(button.dataset.screen));
});
const pageOptions = new URLSearchParams(window.location.search);
const requestedTheme = pageOptions.get('theme');
setWorkspaceTheme(requestedTheme === 'light' ? 'light' : 'dark');
if (pageOptions.get('view') === 'workspace' && workspace) {
  document.documentElement.style.scrollBehavior = 'auto';
  window.addEventListener('load', () => {
    window.requestAnimationFrame(() => workspace.scrollIntoView());
  }, { once: true });
}

const featureTags = {
  zh: [['PDF / Word', '页面管理', '多标签'], ['文字图像', '签名设计', '批注标记'], ['OCR', 'AES-256', '水印']],
  en: [['PDF / Word', 'Page tools', 'Multiple tabs'], ['Text & images', 'Signature design', 'Annotations'], ['OCR', 'AES-256', 'Watermarks']]
};

const setLanguage = language => {
  const lang = language === 'en' ? 'en' : 'zh';
  currentLanguage = lang;
  const selectedCopy = copy[lang];
  document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
  document.title = selectedCopy.title;
  document.querySelector('meta[name="description"]')?.setAttribute('content', selectedCopy.description);

  Object.entries(selectedCopy.texts).forEach(([selector, value]) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  });
  Object.entries(selectedCopy.html).forEach(([selector, value]) => {
    const element = document.querySelector(selector);
    if (element) element.innerHTML = value;
  });
  document.querySelectorAll('.feature-row').forEach((row, rowIndex) => {
    row.querySelectorAll('li').forEach((tag, tagIndex) => {
      tag.textContent = featureTags[lang][rowIndex][tagIndex];
    });
  });

  if (screenButtons[0]?.lastChild) screenButtons[0].lastChild.nodeValue = lang === 'en' ? 'Light' : '浅色界面';
  if (screenButtons[1]?.lastChild) screenButtons[1].lastChild.nodeValue = lang === 'en' ? 'Dark' : '深色界面';
  const footerCopy = document.querySelector('.footer-inner > p');
  if (footerCopy) footerCopy.innerHTML = `© <span id="year">${new Date().getFullYear()}</span> RAY · ${lang === 'en' ? 'A clear, focused PDF reader and editor' : '清晰、专注的 PDF 阅读与编辑工具'}`;
  document.querySelector('.theme-switch')?.setAttribute('aria-label', lang === 'en' ? 'Switch application screenshot theme' : '切换软件截图主题');
  document.querySelector('.language-switch')?.setAttribute('aria-label', lang === 'en' ? 'Website language' : '网站语言');
  document.querySelectorAll('.title-app span').forEach(title => { title.textContent = lang === 'en' ? 'DO Editor — Product Overview' : 'DO编辑器 — Product Overview'; });
  if (heroScreen) {
    heroScreen.src = screenshots[lang].dark;
    heroScreen.alt = lang === 'en' ? 'DO Editor dark interface preview' : 'DO编辑器深色界面预览';
  }
  setWorkspaceTheme(workspace?.dataset.theme || 'dark');

  languageButtons.forEach(button => {
    const active = button.dataset.language === lang;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  try { localStorage.setItem('do-editor-site-language', lang); } catch {}
};

languageButtons.forEach(button => button.addEventListener('click', () => setLanguage(button.dataset.language)));
let savedLanguage = '';
try { savedLanguage = localStorage.getItem('do-editor-site-language') || ''; } catch {}
setLanguage(pageOptions.get('lang') || savedLanguage || 'zh');

const year = document.querySelector('#year');
if (year) year.textContent = String(new Date().getFullYear());
