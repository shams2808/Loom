// Loom Review (PR Review Mode) Controller
// Manages scraping diffs from the GitHub page, executing reviews,
// rendering summary statistics, and inserting inline comment cards into diff tables.

(function() {
  let shadow = null;
  let currentRepoName = null;
  let activeRepoId = null;

  // Loom Icon SVG for inline comments
  const LOOM_SVG_ICON = `
    <svg class="loom-inline-icon" viewBox="0 0 100 100" width="14" height="14" style="display:inline-block; vertical-align: middle; fill: none; stroke: currentColor; stroke-width: 8; stroke-linecap: round; stroke-linejoin: round;">
      <path d="M 30,30 C 15,45 15,55 30,70 C 45,85 55,85 70,70 C 85,55 85,45 70,30 C 55,15 45,15 30,30 Z"/>
      <path d="M 70,30 C 85,45 85,55 70,70 C 55,85 45,85 30,70 C 15,55 15,45 30,30 C 45,15 55,15 70,30 Z"/>
    </svg>
  `;

  // Inject CSS styles into the host page head (since scoped Shadow DOM CSS cannot style native diff tables)
  function injectHostStyles() {
    if (document.getElementById('loom-injected-styles')) return;

    const styleEl = document.createElement('style');
    styleEl.id = 'loom-injected-styles';
    styleEl.textContent = `
      .loom-comment-row {
        background-color: #f6f8fa !important;
      }
      .loom-comment-row.loom-dark {
        background-color: #161b22 !important;
      }
      .loom-inline-comment-container {
        display: block;
        margin: 8px 16px 8px 72px; /* aligns with code cells */
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #d0d7de;
        background-color: #ffffff;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        font-size: 13px;
        line-height: 1.5;
        color: #24292f;
      }
      .loom-inline-comment-container.loom-dark {
        border-color: #30363d !important;
        background-color: #0d1117 !important;
        color: #c9d1d9 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
      }
      .loom-comment-header {
        display: flex;
        align-items: center;
        margin-bottom: 6px;
        font-weight: 600;
        font-size: 12.5px;
      }
      .loom-comment-author {
        color: #57606a;
        margin-left: 6px;
        font-weight: 600;
      }
      .loom-inline-comment-container.loom-dark .loom-comment-author {
        color: #8b949e;
      }
      .loom-comment-badge {
        padding: 2px 6px;
        border-radius: 12px;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 700;
        margin-left: 8px;
      }
      .loom-badge-info {
        background-color: #ddf4ff;
        color: #0969da;
      }
      .loom-inline-comment-container.loom-dark .loom-badge-info {
        background-color: rgba(56, 139, 253, 0.15);
        color: #58a6ff;
      }
      .loom-badge-warning {
        background-color: #fff8c5;
        color: #9a6700;
      }
      .loom-inline-comment-container.loom-dark .loom-badge-warning {
        background-color: rgba(210, 153, 34, 0.15);
        color: #d29922;
      }
      .loom-badge-critical, .loom-badge-error {
        background-color: #ffebe9;
        color: #cf222e;
      }
      .loom-inline-comment-container.loom-dark .loom-badge-critical,
      .loom-inline-comment-container.loom-dark .loom-badge-error {
        background-color: rgba(248, 81, 73, 0.15);
        color: #f85149;
      }
      .loom-comment-body {
        margin-top: 6px;
        white-space: pre-wrap;
        font-weight: 400;
        line-height: 1.45;
      }
      .loom-inline-icon {
        margin-right: 4px;
        vertical-align: middle;
        filter: drop-shadow(0 0 3px rgba(163, 114, 255, 0.6));
        animation: loom-icon-pulse 3s infinite alternate;
      }
      @keyframes loom-icon-pulse {
        from { filter: drop-shadow(0 0 2px rgba(163, 114, 255, 0.4)); }
        to { filter: drop-shadow(0 0 6px rgba(163, 114, 255, 0.8)); }
      }
    `;
    document.head.appendChild(styleEl);
  }

  // Parse simple Markdown for results summary text
  function parseSummaryMarkdown(text) {
    if (!text) return "";
    
    const isDark = document.documentElement.getAttribute("data-color-mode") === "dark" || 
                   document.documentElement.getAttribute("data-dark-theme") !== null ||
                   document.documentElement.classList.contains("dark");

    let html = text
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.*?)`/g, `<code style="background: rgba(128,128,128,0.18); padding: 1.5px 4px; border-radius: 4px; font-family: monospace; font-size: 0.88em; color: ${isDark ? "#ff7b72" : "#cf222e"};">$1</code>`);

    const lines = html.split("\n");
    let resultHtml = "";
    let inList = false;

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) continue;

      const isBullet = line.startsWith("* ") || line.startsWith("- ");
      if (isBullet) {
        if (!inList) {
          resultHtml += "<ul style='margin: 8px 0; padding-left: 20px; list-style-type: disc;'>";
          inList = true;
        }
        resultHtml += `<li style='margin-bottom: 5px; font-size: 13px;'>${line.substring(2)}</li>`;
      } else {
        if (inList) {
          resultHtml += "</ul>";
          inList = false;
        }
        resultHtml += `<p style='margin: 8px 0; line-height: 1.5; font-size: 13px;'>${line}</p>`;
      }
    }

    if (inList) {
      resultHtml += "</ul>";
    }

    return resultHtml;
  }

  // Scrape Unified Diff blocks from GitHub DOM
  function extractDiffFromDOM() {
    const pathParts = window.location.pathname.split('/');
    const repo_id = (pathParts[1] && pathParts[2]) ? `${pathParts[1]}/${pathParts[2]}` : "";
    
    const titleEl = document.querySelector(".js-issue-title") || 
                    document.querySelector(".pr-header-directory .title") || 
                    document.querySelector("h1.gh-header-title");
    const pr_title = titleEl ? titleEl.textContent.trim() : "Untitled PR";
    
    const descEl = document.querySelector(".js-comment-body");
    const pr_description = descEl ? descEl.textContent.trim() : "";
    
    const diffMap = new Map(); // file_path -> { status: string, lines: array }
    
    // Helper to extract file path from file header block
    function extractPath(header) {
      let filePath = header.getAttribute("data-file-path") || header.closest("[data-file-path]")?.getAttribute("data-file-path");
      if (filePath) return filePath.trim();
      
      const titleLink = header.querySelector("a[title]");
      if (titleLink) {
        const t = titleLink.getAttribute("title");
        if (t) return t.trim();
      }
      
      const primaryLink = header.querySelector("a.Link--primary, h3 a, h4 a");
      if (primaryLink) return primaryLink.textContent.trim();
      
      const clipboardEl = header.querySelector("[data-clipboard-text]");
      if (clipboardEl) return clipboardEl.getAttribute("data-clipboard-text").trim();
      
      const anyLink = header.querySelector("a, code");
      if (anyLink) return anyLink.textContent.trim();
      
      return "";
    }

    // 1. Scan code lines globally
    const codeCells = document.querySelectorAll(".diff-text-inner, .blob-code-inner, code.diff-text, td.diff-text-cell, .blob-code");
    console.log(`[Loom Review] Found ${codeCells.length} code cells in page DOM.`);
    
    codeCells.forEach((codeCell) => {
      let container = codeCell.parentElement;
      let header = null;
      while (container && container.parentElement && container.parentElement !== document.body) {
        header = container.querySelector(".file-header, [class*='file-header'], [class*='diff-file-header'], [class*='diffHeaderWrapper'], .js-file-header");
        if (header) break;
        container = container.parentElement;
      }
      
      if (!container || !header) return;
      
      const filePath = extractPath(header);
      if (!filePath) return;
      
      if (!diffMap.has(filePath)) {
        let status = "modified";
        const headerText = header.textContent.toLowerCase();
        const isDeleted = container.querySelector('.diffstat-status-deleted') !== null || headerText.includes("deleted");
        const isAdded = container.querySelector('.diffstat-status-added') !== null || headerText.includes("added");
        const isRenamed = container.querySelector('.diffstat-status-renamed') !== null || headerText.includes("→") || headerText.includes("renamed");
        
        if (isDeleted) status = "removed";
        else if (isAdded) status = "added";
        else if (isRenamed) status = "renamed";
        
        diffMap.set(filePath, { status: status, lines: [] });
      }
      
      const fileDiff = diffMap.get(filePath);
      
      if (codeCell.classList.contains("blob-code-hunk") || codeCell.closest(".blob-code-hunk")) {
        fileDiff.lines.push(codeCell.textContent.trim());
        return;
      }
      
      let marker = "";
      const codeRow = codeCell.closest("tr, [class*='row'], [class*='line']");
      const codeContainer = codeCell.closest("code, td, div");
      
      const classStr = (
        codeCell.className + " " + 
        (codeContainer ? codeContainer.className : "") + " " + 
        (codeRow ? codeRow.className : "")
      ).toLowerCase();
      
      if (classStr.includes("addition") || classStr.includes("added") || classStr.includes("add")) {
        marker = "+";
      } else if (classStr.includes("deletion") || classStr.includes("removed") || classStr.includes("deleted") || classStr.includes("removal") || classStr.includes("del")) {
        marker = "-";
      } else {
        marker = codeCell.getAttribute("data-code-marker") || codeContainer?.getAttribute("data-code-marker") || " ";
      }
      
      const codeText = codeCell.textContent || "";
      fileDiff.lines.push(marker + codeText);
    });

    // 2. Auto-expand collapsed diff blocks
    const loadButtons = document.querySelectorAll('.js-diff-load-button, button.load-diff-button, .load-diff-container button');
    loadButtons.forEach((button) => {
      let container = button.parentElement;
      let header = null;
      while (container && container.parentElement && container.parentElement !== document.body) {
        header = container.querySelector(".file-header, [class*='file-header'], [class*='diff-file-header'], [class*='diffHeaderWrapper'], .js-file-header");
        if (header) break;
        container = container.parentElement;
      }
      
      if (!container || !header) return;
      
      const filePath = extractPath(header);
      if (!filePath) return;
      
      button.click(); // Expand
      
      if (!diffMap.has(filePath)) {
        diffMap.set(filePath, {
          status: "modified",
          lines: ["COLLAPSED_UNAVAILABLE: File was collapsed. Expanding file now... Please try reviewing again."]
        });
      }
    });

    const diffs = [];
    diffMap.forEach((val, key) => {
      diffs.push({
        file: key,
        patch: val.lines.join("\n"),
        status: val.status
      });
    });
    
    return {
      repo_id: repo_id,
      pr_title: pr_title,
      pr_description: pr_description,
      diff: diffs
    };
  }

  // Inject inline review comments in diff tables
  function renderInlineComments(comments) {
    // 1. Remove existing Loom comments first
    document.querySelectorAll(".loom-inline-comment-container").forEach(el => el.remove());
    
    if (!comments || !comments.length) return;
    
    function extractPath(container) {
      let filePath = container.getAttribute("data-file-path");
      if (filePath) return filePath.trim();
      
      const header = container.querySelector(".file-header, [class*='file-header'], [class*='diff-file-header'], [class*='diffHeaderWrapper'], .js-file-header");
      if (header) {
        const titleLink = header.querySelector("a[title]");
        if (titleLink) return titleLink.getAttribute("title").trim();
        
        const primaryLink = header.querySelector("a.Link--primary, h3 a, h4 a");
        if (primaryLink) return primaryLink.textContent.trim();
        
        const clipboardEl = header.querySelector("[data-clipboard-text]");
        if (clipboardEl) return clipboardEl.getAttribute("data-clipboard-text").trim();
        
        const anyLink = header.querySelector("a, code");
        if (anyLink) return anyLink.textContent.trim();
      }
      return "";
    }
    
    const headers = document.querySelectorAll(".file-header, [class*='file-header'], [class*='diff-file-header'], [class*='diffHeaderWrapper'], .js-file-header");
    const fileBlocks = [];
    
    headers.forEach(header => {
      const filePath = extractPath(header);
      if (!filePath) return;
      
      let container = header;
      while (container && container.parentElement && container.parentElement !== document.body) {
        if (container.parentElement.querySelector(".blob-code-inner, .blob-code, [class*='blob-code'], [class*='code']")) {
          container = container.parentElement;
          break;
        }
        container = container.parentElement;
      }
      if (container) {
        fileBlocks.push({ file: filePath, container: container });
      }
    });

    const isDark = document.documentElement.getAttribute("data-color-mode") === "dark" || 
                   document.documentElement.getAttribute("data-dark-theme") !== null ||
                   document.documentElement.classList.contains("dark");

    comments.forEach(comment => {
      const cleanCommentFile = comment.file.replace(/\\/g, "/").toLowerCase();
      
      const block = fileBlocks.find(b => {
        const cleanBlockFile = b.file.replace(/\\/g, "/").toLowerCase();
        return cleanCommentFile.endsWith(cleanBlockFile) || 
               cleanBlockFile.endsWith(cleanCommentFile) ||
               cleanCommentFile.includes(cleanBlockFile) ||
               cleanBlockFile.includes(cleanCommentFile);
      });
      
      if (!block) {
        console.warn(`[Loom Review] Could not find file container matching: ${comment.file}`);
        return;
      }
      
      const targetContainer = block.container;
      const rows = targetContainer.querySelectorAll("tr, [class*='line-row'], [class*='diff-line-row']");
      let targetRow = null;
      
      for (const row of rows) {
        const numCells = Array.from(row.querySelectorAll("td, th, [role='gridcell']")).filter(cell => {
          const cls = (cell.className || "").toLowerCase();
          return cell.hasAttribute("data-line-number") || 
                 cls.includes("line-number") || 
                 cls.includes("num") || 
                 /^\d+$/.test(cell.textContent.trim());
        });
        
        if (numCells.length >= 2) {
          const newLineCell = numCells[1];
          const lineAttr = newLineCell.getAttribute("data-line-number") || newLineCell.getAttribute("data-line");
          const lineText = newLineCell.textContent.trim();
          
          if (lineAttr === String(comment.line) || lineText === String(comment.line)) {
            const cellClass = newLineCell.className.toLowerCase();
            // Don't insert into deleted code rows
            if (lineText !== "" && !cellClass.includes("delete") && !cellClass.includes("removal") && !cellClass.includes("deleted")) {
              targetRow = row;
              break;
            }
          }
        } else if (numCells.length === 1) {
          const cell = numCells[0];
          const lineAttr = cell.getAttribute("data-line-number") || cell.getAttribute("data-line");
          const lineText = cell.textContent.trim();
          
          if (lineAttr === String(comment.line) || lineText === String(comment.line)) {
            targetRow = row;
            break;
          }
        }
      }
      
      if (!targetRow) {
        console.warn(`[Loom Review] Could not find row matching line: ${comment.line} in file ${comment.file}`);
        return;
      }
      
      const codeCell = targetRow.querySelector("td.diff-text-cell, td.blob-code, [class*='code-cell'], [class*='blob-code']");
      if (!codeCell) {
        console.warn(`[Loom Review] Could not find code cell inside target row for line: ${comment.line}`);
        return;
      }
      
      const commentDiv = document.createElement("div");
      commentDiv.className = `loom-inline-comment-container ${isDark ? "loom-dark" : "loom-light"}`;
      
      const sev = (comment.severity || "info").toLowerCase();
      // Ensure mapped correctly to info/warning/critical
      const severityClass = `loom-badge-${sev}`;
      const severityText = sev.toUpperCase();
      
      commentDiv.innerHTML = `
        <div class="loom-comment-header">
          ${LOOM_SVG_ICON}
          <span class="loom-comment-author">Loom Review</span>
          <span class="loom-comment-badge ${severityClass}">${severityText}</span>
        </div>
        <div class="loom-comment-body">${comment.text}</div>
      `;
      
      codeCell.appendChild(commentDiv);
      console.log(`[Loom Review] Inline comment injected on line ${comment.line} of ${comment.file}`);
    });
  }

  const Review = {
    init: function(shadowRoot) {
      shadow = shadowRoot;
      injectHostStyles();
      this.bindEvents();
    },

    bindEvents: function() {
      // 1. Run Review Button
      const runBtn = shadow.getElementById('loom-run-review-btn');
      if (runBtn) {
        runBtn.addEventListener('click', () => this.executePRReview());
      }

      // 2. Re-run Review Button
      const rerunBtn = shadow.getElementById('loom-re-review-btn');
      if (rerunBtn) {
        rerunBtn.addEventListener('click', () => this.executePRReview());
      }

      // 3. Clear Comments Button
      const clearBtn = shadow.getElementById('loom-clear-comments-btn');
      if (clearBtn) {
        clearBtn.addEventListener('click', () => {
          document.querySelectorAll(".loom-inline-comment-container").forEach(el => el.remove());
          alert("All inline review comments cleared.");
        });
      }
    },

    onActivate: function(repoName) {
      currentRepoName = repoName;
      activeRepoId = null;

      // Reset display states
      this.toggleStateCards('initial');

      // Check if current repo is indexed to set context-aware notice
      if (repoName) {
        chrome.runtime.sendMessage({
          type: 'API_REQUEST',
          path: '/repos/indexed'
        }, (response) => {
          const noteEl = shadow.getElementById('loom-review-context-note');
          if (response && response.success && response.result && response.result.ok) {
            const repos = response.result.data.repos || [];
            const matchedRepo = repos.find(r => r.repo_full_name.toLowerCase() === repoName.toLowerCase());
            
            if (matchedRepo && matchedRepo.status === 'ready') {
              activeRepoId = matchedRepo.repo_id;
              if (noteEl) {
                noteEl.innerHTML = `Loom codebase index is ready. Review will run in <strong>Context-Aware</strong> mode.`;
              }
            } else {
              if (noteEl) {
                noteEl.innerHTML = `Loom codebase index not found. Review will run in <strong>Basic</strong> mode.`;
              }
            }
          } else {
            if (noteEl) {
              noteEl.innerHTML = `Loom codebase index not found. Review will run in <strong>Basic</strong> mode.`;
            }
          }
        });
      }
    },

    toggleStateCards: function(state) {
      const initial = shadow.getElementById('loom-review-initial');
      const loading = shadow.getElementById('loom-review-loading');
      const results = shadow.getElementById('loom-review-results');

      if (initial) initial.style.display = 'none';
      if (loading) loading.style.display = 'none';
      if (results) results.style.display = 'none';

      if (state === 'initial') {
        if (initial) initial.style.display = 'flex';
      } else if (state === 'loading') {
        if (loading) loading.style.display = 'flex';
      } else if (state === 'results') {
        if (results) results.style.display = 'flex';
      }
    },

    // Execute review flow
    executePRReview: function() {
      // 1. Extract diff content from page DOM
      let payload;
      try {
        payload = extractDiffFromDOM();
      } catch (e) {
        console.error("DOM Extraction failed:", e);
        alert(`Extraction failed: ${e.message}`);
        return;
      }

      if (!payload || !payload.diff || payload.diff.length === 0) {
        alert("No files extracted. Please make sure you are on the 'Files changed' tab of the pull request.");
        return;
      }

      // 2. Show Loading State
      this.toggleStateCards('loading');

      // 3. Dispatch POST /review
      chrome.runtime.sendMessage({
        type: 'API_REQUEST',
        method: 'POST',
        path: '/review',
        body: {
          repo_id: activeRepoId, // Pass matching UUID or null
          pr_title: payload.pr_title,
          pr_description: payload.pr_description,
          diff: payload.diff
        }
      }, (response) => {
        if (response && response.success && response.result && response.result.ok) {
          const data = response.result.data;

          // 4. Render inline comments
          renderInlineComments(data.comments);

          // 5. Render stats and summary details
          this.renderReviewOutcome(data);
          this.toggleStateCards('results');
        } else {
          this.toggleStateCards('initial');
          const errorMsg = (response && response.result && response.result.data && response.result.data.error)
            ? response.result.data.error
            : "Running review failed. Make sure backend is running.";
          alert(`Review Error: ${errorMsg}`);
        }
      });
    },

    // Render outcome results, counts, and categories
    renderReviewOutcome: function(data) {
      const errCountEl = shadow.getElementById('loom-count-error');
      const warnCountEl = shadow.getElementById('loom-count-warning');
      const infoCountEl = shadow.getElementById('loom-count-info');
      const badgeEl = shadow.getElementById('loom-context-badge');
      const bodyEl = shadow.getElementById('loom-results-body');

      // 1. Calculate comments metrics (critical/warning/info)
      let critical = 0;
      let warnings = 0;
      let infos = 0;

      if (data.comments && Array.isArray(data.comments)) {
        data.comments.forEach(c => {
          const sev = (c.severity || "").toLowerCase();
          if (sev === "critical" || sev === "error") critical++;
          else if (sev === "warning") warnings++;
          else if (sev === "info") infos++;
        });
      }

      if (errCountEl) errCountEl.textContent = critical;
      if (warnCountEl) warnCountEl.textContent = warnings;
      if (infoCountEl) infoCountEl.textContent = infos;

      // 2. Set Context badge
      if (badgeEl) {
        if (data.context_aware) {
          badgeEl.textContent = "Context-Aware";
          badgeEl.className = "loom-context-badge";
        } else {
          badgeEl.textContent = "Basic Review";
          badgeEl.className = "loom-context-badge loom-badge-basic";
        }
      }

      // 3. Render summary body (collapsible detail containers if JSON, else markdown string)
      let summaryHtml = "";
      if (typeof data.summary === "object" && data.summary !== null) {
        const categoryIcons = {
          "Core Changes": "📂",
          "Architectural Impact": "🏗️",
          "Testing & Verification": "🧪"
        };

        for (const [category, items] of Object.entries(data.summary)) {
          const icon = categoryIcons[category] || "📝";
          let detailsContent = "";

          if (Array.isArray(items)) {
            detailsContent += "<ol style='margin: 0; padding-left: 20px;'>";
            items.forEach(item => {
              detailsContent += `<li style='margin-bottom: 5px;'>${item}</li>`;
            });
            detailsContent += "</ol>";
          } else {
            detailsContent += `<p style='margin: 0;'>${items}</p>`;
          }

          summaryHtml += `
            <details>
              <summary>
                <span>${icon} ${category}</span>
                <span class="loom-accordion-marker">▶</span>
              </summary>
              <div class="loom-accordion-content">
                ${detailsContent}
              </div>
            </details>
          `;
        }
      } else {
        // Fallback: parse as standard string markdown
        summaryHtml = parseSummaryMarkdown(data.summary);
      }

      if (bodyEl) {
        bodyEl.innerHTML = summaryHtml;
      }
    }
  };

  // Export globally to window
  window.LoomReview = Review;
})();
