// Loom Content Script
// Handles sidebar injection, toggle interactions, body page-shifting,
// URL changes monitoring (GitHub SPA), and mode switching.

let shadowRoot = null;
let currentMode = 'hidden'; // 'qa' | 'review' | 'hidden'
let isSidebarOpen = false;

// 1. URL Detection & Mode Mapping
function detectPageMode(pathname) {
  // PR page → Review mode
  if (/^\/[^/]+\/[^/]+\/pull\/\d+/.test(pathname)) {
    return 'review';
  }
  // Repo page (home, code, file view, commits) → QA mode
  const pathParts = pathname.split('/').filter(Boolean);
  if (pathParts.length >= 2) {
    // Exclude general GitHub paths
    const excluded = ['settings', 'notifications', 'explore', 'trending', 'sponsors', 'marketplace', 'issues', 'pulls'];
    if (!excluded.includes(pathParts[0])) {
      return 'qa';
    }
  }
  return 'hidden';
}

// 2. Extract Repo owner/name from URL
function getRepoFullname() {
  const match = window.location.pathname.match(/^\/([^/]+\/[^/]+)/);
  if (match) {
    const parts = match[1].split('/');
    if (parts.length === 2 && !['settings', 'notifications', 'orgs'].includes(parts[0])) {
      return match[1];
    }
  }
  return null;
}

// 3. Inject Sidebar and Toggle Button into GitHub DOM
async function injectLoom() {
  if (document.getElementById('loom-sidebar-root')) return;

  // Create Root Container
  const container = document.createElement('div');
  container.id = 'loom-sidebar-root';
  container.style.position = 'fixed';
  container.style.top = '0';
  container.style.right = '0';
  container.style.height = '100vh';
  container.style.zIndex = '2147483647'; // Maximum possible z-index
  document.body.appendChild(container);

  // Attach Shadow DOM
  shadowRoot = container.attachShadow({ mode: 'open' });

  // Load Stylesheet inside Shadow DOM
  const cssUrl = chrome.runtime.getURL('panel/panel.css');
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = cssUrl;
  shadowRoot.appendChild(link);

  // Load HTML template
  const htmlUrl = chrome.runtime.getURL('panel/panel.html');
  const response = await fetch(htmlUrl);
  const htmlText = await response.text();

  const wrapper = document.createElement('div');
  wrapper.id = 'loom-panel-wrapper';
  wrapper.className = 'loom-sidebar';
  wrapper.innerHTML = htmlText;
  shadowRoot.appendChild(wrapper);

  // Inject Toggle Badge into Main Document Body
  injectToggleBadge();

  // Setup Event Listeners inside Shadow DOM
  setupPanelListeners();

  // Initialize QA & Review modules
  if (window.LoomQA && typeof window.LoomQA.init === 'function') {
    window.LoomQA.init(shadowRoot);
  }
  if (window.LoomReview && typeof window.LoomReview.init === 'function') {
    window.LoomReview.init(shadowRoot);
  }

  // Initial Auth Check & Render
  checkAuthAndRefresh();
}

// Inject the floating toggle badge on the page edge
function injectToggleBadge() {
  if (document.getElementById('loom-toggle-badge-root')) return;

  const btn = document.createElement('div');
  btn.id = 'loom-toggle-badge-root';
  btn.style.position = 'fixed';
  btn.style.right = '0';
  btn.style.top = '50%';
  btn.style.transform = 'translateY(-50%)';
  btn.style.zIndex = '2147483646';
  btn.style.cursor = 'pointer';

  // Loom Logo Icon (SVG)
  btn.innerHTML = `
    <div style="
      background: #8a2be2;
      color: #ffffff;
      padding: 10px 8px;
      border-radius: 8px 0 0 8px;
      box-shadow: -2px 0 8px rgba(0, 0, 0, 0.2);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      font-weight: bold;
      font-size: 10px;
      letter-spacing: 1px;
      transition: all 0.2s ease-in-out;
      user-select: none;
    ">
      <svg viewBox="0 0 100 100" width="16" height="16" style="fill: none; stroke: currentColor; stroke-width: 10; stroke-linecap: round; stroke-linejoin: round;">
        <path d="M 30,30 C 15,45 15,55 30,70 C 45,85 55,85 70,70 C 85,55 85,45 70,30 C 55,15 45,15 30,30 Z"/>
        <path d="M 70,30 C 85,45 85,55 70,70 C 55,85 45,85 30,70 C 15,55 15,45 30,30 C 45,15 55,15 70,30 Z"/>
      </svg>
      <div style="writing-mode: vertical-rl; text-orientation: mixed;">LOOM</div>
    </div>
  `;

  btn.addEventListener('mouseenter', () => {
    btn.firstElementChild.style.background = '#a372ff';
    btn.firstElementChild.style.paddingRight = '12px';
  });

  btn.addEventListener('mouseleave', () => {
    btn.firstElementChild.style.background = '#8a2be2';
    btn.firstElementChild.style.paddingRight = '6px';
  });

  btn.addEventListener('click', toggleSidebar);
  document.body.appendChild(btn);
}

// Set up UI Event Listeners (close button, etc.)
function setupPanelListeners() {
  const closeBtn = shadowRoot.getElementById('loom-close-btn');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => setSidebarOpen(false));
  }

  const loginBtn = shadowRoot.getElementById('loom-login-btn');
  if (loginBtn) {
    loginBtn.addEventListener('click', () => {
      chrome.runtime.sendMessage({
        type: 'API_REQUEST',
        path: '/auth/github/login'
      }, (response) => {
        const loginUrl = "http://localhost:8000/auth/github/login";
        chrome.runtime.sendMessage({
          type: 'API_REQUEST',
          path: '/auth/me'
        }, () => {
          window.open(loginUrl, '_blank');
        });
      });
    });
  }
}

// Theme adaptation check helper
function isDarkMode() {
  const mode = document.documentElement.getAttribute("data-color-mode");
  if (mode === "dark") return true;
  if (mode === "auto") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  return document.documentElement.getAttribute("data-dark-theme") !== null ||
         document.documentElement.classList.contains("dark") ||
         document.body.classList.contains("dark");
}

// Synchronizes the visual variables in Shadow DOM to match GitHub theme
function updateTheme() {
  const wrapper = shadowRoot?.getElementById('loom-panel-wrapper');
  if (wrapper) {
    if (isDarkMode()) {
      wrapper.classList.remove('loom-light');
      wrapper.classList.add('loom-dark');
    } else {
      wrapper.classList.remove('loom-dark');
      wrapper.classList.add('loom-light');
    }
  }
}


// Check auth token and adjust profile/avatar representation
function checkAuthAndRefresh() {
  chrome.runtime.sendMessage({
    type: 'API_REQUEST',
    path: '/auth/me'
  }, (response) => {
    const header = shadowRoot.getElementById('loom-header');
    const authBox = shadowRoot.getElementById('loom-auth-section');
    const contentBox = shadowRoot.getElementById('loom-mode-content');
    
    if (response && response.success && response.result && response.result.ok) {
      const user = response.result.data;
      
      // Update Header with Avatar
      const avatarContainer = shadowRoot.getElementById('loom-avatar-container');
      if (avatarContainer) {
        avatarContainer.innerHTML = `
          <img src="${user.avatar_url}" alt="${user.github_username}" style="
            width: 28px;
            height: 28px;
            border-radius: 50%;
            border: 1px solid rgba(255,255,255,0.2);
          " title="${user.github_username}" />
        `;
      }
      
      // Show content, hide login
      if (authBox) authBox.style.display = 'none';
      if (contentBox) contentBox.style.display = 'block';

      // Update Current Mode
      updateModeView();
    } else {
      // Unauthenticated
      const avatarContainer = shadowRoot.getElementById('loom-avatar-container');
      if (avatarContainer) avatarContainer.innerHTML = '';
      
      if (authBox) authBox.style.display = 'flex';
      if (contentBox) contentBox.style.display = 'none';
    }
  });
}

// Handle layout shifting when opening/closing the sidebar
function setSidebarOpen(open) {
  isSidebarOpen = open;
  const wrapper = shadowRoot?.getElementById('loom-panel-wrapper');
  const toggleBtn = document.getElementById('loom-toggle-badge-root');

  if (open) {
    updateTheme(); // Ensure theme is fresh on slide-in
    wrapper?.classList.add('open');
    if (toggleBtn) toggleBtn.style.display = 'none';
    
    // Shift GitHub content
    document.body.style.transition = 'margin-right 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
    document.body.style.marginRight = '380px';
  } else {
    wrapper?.classList.remove('open');
    // Reveal toggle badge after transition
    setTimeout(() => {
      if (!isSidebarOpen && toggleBtn) toggleBtn.style.display = 'block';
    }, 300);

    // Un-shift GitHub content
    document.body.style.marginRight = '0px';
  }
}

function toggleSidebar() {
  setSidebarOpen(!isSidebarOpen);
}

// Update the visual representation inside the sidebar based on URL state
function updateModeView() {
  updateTheme(); // Keep theme variable aligned
  const mode = detectPageMode(window.location.pathname);
  currentMode = mode;

  const qaSection = shadowRoot.getElementById('loom-qa-mode');
  const reviewSection = shadowRoot.getElementById('loom-review-mode');
  const hiddenSection = shadowRoot.getElementById('loom-hidden-mode');
  const repoNameEl = shadowRoot.getElementById('loom-repo-name');

  // Hide all first
  if (qaSection) qaSection.style.display = 'none';
  if (reviewSection) reviewSection.style.display = 'none';
  if (hiddenSection) hiddenSection.style.display = 'none';

  // If page is hidden, hide the entire sidebar wrapper/toggle
  const rootContainer = document.getElementById('loom-sidebar-root');
  const toggleBtn = document.getElementById('loom-toggle-badge-root');

  if (mode === 'hidden') {
    if (rootContainer) rootContainer.style.display = 'none';
    if (toggleBtn) toggleBtn.style.display = 'none';
    setSidebarOpen(false);
    return;
  }

  // Display elements
  if (rootContainer) rootContainer.style.display = 'block';
  // If sidebar is closed, keep toggle badge visible
  if (toggleBtn && !isSidebarOpen) toggleBtn.style.display = 'block';

  // Set header repo title
  const repoName = getRepoFullname();
  if (repoNameEl) {
    repoNameEl.textContent = repoName || 'Loom Workspace';
  }

  if (mode === 'qa') {
    if (qaSection) qaSection.style.display = 'flex';
    if (window.LoomQA && typeof window.LoomQA.onActivate === 'function') {
      window.LoomQA.onActivate(repoName);
    }
  } else if (mode === 'review') {
    if (reviewSection) reviewSection.style.display = 'flex';
    if (window.LoomReview && typeof window.LoomReview.onActivate === 'function') {
      window.LoomReview.onActivate(repoName);
    }
  }
}

// 4. Monitoring Navigation in GitHub SPA
let lastPathname = location.pathname;
const observer = new MutationObserver(() => {
  if (location.pathname !== lastPathname) {
    lastPathname = location.pathname;
    console.log("Loom detected navigation to:", lastPathname);
    // Let DOM render, then update
    setTimeout(() => {
      updateModeView();
    }, 500);
  }
});

// Start observer once title is present
function startNavigationObserver() {
  const titleEl = document.querySelector('title');
  if (titleEl) {
    observer.observe(titleEl, { childList: true });
  } else {
    setTimeout(startNavigationObserver, 500);
  }
}

// 5. Initialize Page Scripts
function init() {
  const mode = detectPageMode(window.location.pathname);
  if (mode !== 'hidden') {
    injectLoom();
  }
  startNavigationObserver();
}

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// 6. Listeners for Background notifications (Auth changes, etc.)
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'AUTH_UPDATED') {
    console.log("Loom received AUTH_UPDATED notification. Refreshing auth state...");
    checkAuthAndRefresh();
    sendResponse({ success: true });
  }
});
