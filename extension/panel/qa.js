// Loom QA (Q&A Mode) Controller
// Manages repository status checking, indexing trigger, progress polling,
// and Q&A chat loops inside the sidebar.

(function() {
  let shadow = null;
  let currentRepoName = null;
  let activeRepoId = null;
  let activeConversationId = null;
  let pollIntervalId = null;

  const QA = {
    init: function(shadowRoot) {
      shadow = shadowRoot;
      this.bindEvents();
    },

    bindEvents: function() {
      // 1. Index Button Click
      const indexBtn = shadow.getElementById('loom-index-btn');
      if (indexBtn) {
        indexBtn.addEventListener('click', () => this.triggerIndexing());
      }

      // 2. Chat Send Button Click
      const sendBtn = shadow.getElementById('loom-chat-send');
      if (sendBtn) {
        sendBtn.addEventListener('click', () => this.sendChatMessage());
      }

      // 3. Chat Input Keydown (Enter to send)
      const chatInput = shadow.getElementById('loom-chat-input');
      if (chatInput) {
        chatInput.addEventListener('keydown', (e) => {
          e.stopPropagation();
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            this.sendChatMessage();
          }
        });
        chatInput.addEventListener('keyup', (e) => {
          e.stopPropagation();
        });
        chatInput.addEventListener('keypress', (e) => {
          e.stopPropagation();
        });
      }
    },

    onActivate: function(repoName) {
      if (!repoName) return;
      
      // Reset if switching to a new repository
      if (currentRepoName !== repoName) {
        currentRepoName = repoName;
        activeRepoId = null;
        activeConversationId = null;
        this.clearChatLog();
        this.stopPolling();
      }

      this.checkRepoIndexStatus();
    },

    // Check index status from backend
    checkRepoIndexStatus: function() {
      if (!currentRepoName) return;

      chrome.runtime.sendMessage({
        type: 'API_REQUEST',
        path: '/repos/indexed'
      }, (response) => {
        if (response && response.success && response.result && response.result.ok) {
          const repos = response.result.data.repos || [];
          const matchedRepo = repos.find(r => r.repo_full_name.toLowerCase() === currentRepoName.toLowerCase());
          
          if (matchedRepo) {
            activeRepoId = matchedRepo.repo_id;
            this.handleRepoStatus({
              status: matchedRepo.status,
              chunk_count: matchedRepo.chunk_count
            });
          } else {
            // Not indexed yet
            this.showStateCard('unindexed');
          }
        } else {
          console.error("Failed to check repository index status:", response);
          this.showStateCard('unindexed'); // fallback
        }
      });
    },

    // Show appropriate sub-view state cards
    showStateCard: function(state) {
      const unindexedCard = shadow.getElementById('loom-qa-unindexed');
      const indexingCard = shadow.getElementById('loom-qa-indexing');
      const readyCard = shadow.getElementById('loom-qa-ready');

      if (unindexedCard) unindexedCard.style.display = 'none';
      if (indexingCard) indexingCard.style.display = 'none';
      if (readyCard) readyCard.style.display = 'none';

      if (state === 'unindexed') {
        if (unindexedCard) unindexedCard.style.display = 'flex';
      } else if (state === 'indexing') {
        if (indexingCard) indexingCard.style.display = 'flex';
      } else if (state === 'ready') {
        if (readyCard) readyCard.style.display = 'flex';
        this.scrollToBottom();
      }
    },

    // Handle states from backend
    handleRepoStatus: function(data) {
      if (!data) return;
      const status = data.status;
      const chunkCount = data.chunk_count || 0;
      const currentBatch = data.current_batch || 0;
      const totalBatches = data.total_batches || 0;
      const filesProcessed = data.files_processed || 0;

      const countEl = shadow.getElementById('loom-index-chunks');
      const statusTextEl = shadow.getElementById('loom-index-status-text');

      if (countEl) countEl.textContent = chunkCount;
      if (statusTextEl) statusTextEl.textContent = status;

      if (status === 'indexing' || status === 'pending') {
        this.showStateCard('indexing');
        this.startPollingStatus();

        // Update progress bar & ETA details
        const percent = totalBatches > 0 ? Math.round((currentBatch / totalBatches) * 100) : 0;
        const progressFill = shadow.getElementById('loom-index-progress-fill');
        const percentEl = shadow.getElementById('loom-index-percent');
        const batchTextEl = shadow.getElementById('loom-index-batch-text');
        const etaEl = shadow.getElementById('loom-index-eta');

        if (progressFill) progressFill.style.width = `${percent}%`;
        if (percentEl) percentEl.textContent = `${percent}%`;
        if (batchTextEl) batchTextEl.textContent = `Batch ${currentBatch} of ${totalBatches} (${filesProcessed} files)`;

        // Estimate remaining time (local ONNX MiniLM runs at ~0.25s per batch)
        const remainingBatches = totalBatches - currentBatch;
        if (remainingBatches > 0) {
          const estimatedSeconds = Math.ceil(remainingBatches * 0.25);
          if (estimatedSeconds >= 60) {
            const mins = Math.floor(estimatedSeconds / 60);
            const secs = estimatedSeconds % 60;
            if (etaEl) etaEl.textContent = `~${mins}m ${secs}s remaining`;
          } else if (estimatedSeconds > 2) {
            if (etaEl) etaEl.textContent = `~${estimatedSeconds}s remaining`;
          } else {
            if (etaEl) etaEl.textContent = '< 2s remaining';
          }
        } else {
          if (etaEl) etaEl.textContent = 'Finalizing...';
        }
      } else if (status === 'ready') {
        this.stopPolling();
        this.showStateCard('ready');
      } else {
        // failed or other
        this.stopPolling();
        this.showStateCard('unindexed');
        const unindexedDesc = shadow.querySelector('#loom-qa-unindexed p');
        if (unindexedDesc) {
          unindexedDesc.textContent = `Indexing failed (status: ${status}). Please click below to try indexing again.`;
        }
      }
    },

    // Trigger repo indexing
    triggerIndexing: function() {
      if (!currentRepoName) return;

      const indexBtn = shadow.getElementById('loom-index-btn');
      if (indexBtn) {
        indexBtn.disabled = true;
        indexBtn.textContent = 'Triggering...';
      }

      chrome.runtime.sendMessage({
        type: 'API_REQUEST',
        method: 'POST',
        path: '/repos/index',
        body: { repo_full_name: currentRepoName }
      }, (response) => {
        if (indexBtn) {
          indexBtn.disabled = false;
          indexBtn.textContent = 'Index This Repo';
        }

        if (response && response.success && response.result && response.result.ok) {
          const data = response.result.data;
          activeRepoId = data.repo_id;
          this.handleRepoStatus(data);
        } else {
          const errorMsg = (response && response.result && response.result.data && response.result.data.error) 
            ? response.result.data.error 
            : "Triggering indexing failed.";
          alert(`Error: ${errorMsg}`);
        }
      });
    },

    // Start polling indexing progress
    startPollingStatus: function() {
      if (pollIntervalId) return;

      pollIntervalId = setInterval(() => {
        if (!activeRepoId) {
          this.stopPolling();
          return;
        }

        chrome.runtime.sendMessage({
          type: 'API_REQUEST',
          path: `/repos/status/${activeRepoId}`
        }, (response) => {
          if (response && response.success && response.result && response.result.ok) {
            const data = response.result.data;
            this.handleRepoStatus(data);
          } else {
            console.error("Error polling repo index status:", response);
            // Don't stop polling on single failure, server might be restarting
          }
        });
      }, 3000);
    },

    stopPolling: function() {
      if (pollIntervalId) {
        clearInterval(pollIntervalId);
        pollIntervalId = null;
      }
    },

    // Chat log handlers
    clearChatLog: function() {
      const log = shadow.getElementById('loom-chat-log');
      if (log) {
        log.innerHTML = `
          <div class="loom-chat-row loom-chat-row-system">
            <div class="loom-message-content">
              Hello! I am Loom. Ask me anything about this repository's codebase structure, implementation details, or where features are located.
            </div>
          </div>
        `;
      }
    },

    scrollToBottom: function() {
      const log = shadow.getElementById('loom-chat-log');
      if (log) {
        log.scrollTop = log.scrollHeight;
      }
    },

    getCurrentlyViewedFilePath: function() {
      const pathname = window.location.pathname;
      const parts = pathname.split('/').filter(Boolean);
      if (parts.length > 4 && parts[2] === 'blob') {
        return parts.slice(4).join('/');
      }
      return null;
    },

    // Parse simple Markdown citations or references in answer text
    formatAnswerText: function(text) {
      if (!text) return "";
      // Escape HTML to prevent injection
      let html = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

      // Replace bold text (**bold**)
      html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
      // Replace inline code (`code`)
      html = html.replace(/`(.*?)`/g, "<code style='background: rgba(128,128,128,0.15); padding: 2px 4px; border-radius: 4px; font-family: monospace; font-size: 0.9em;'>$1</code>");
      
      // Replace newlines
      html = html.replace(/\n/g, "<br>");
      return html;
    },

    // Send Q&A chat message
    sendChatMessage: function() {
      const inputEl = shadow.getElementById('loom-chat-input');
      const question = inputEl?.value.trim();
      
      if (!question || !activeRepoId) return;

      // 1. Clear input
      inputEl.value = '';

      // 2. Render User Message
      const log = shadow.getElementById('loom-chat-log');
      const userMsgDiv = document.createElement('div');
      userMsgDiv.className = 'loom-chat-row loom-chat-row-user';
      userMsgDiv.innerHTML = `
        <div class="loom-message-content">${this.formatAnswerText(question)}</div>
        <div class="loom-pfp-placeholder"></div>
      `;
      log.appendChild(userMsgDiv);
      this.scrollToBottom();

      // 3. Render Loading Indicator Bubble
      const loadingDiv = document.createElement('div');
      loadingDiv.className = 'loom-chat-row loom-chat-row-assistant loom-message-loading';
      loadingDiv.innerHTML = `
        <div class="loom-pfp-placeholder"></div>
        <div class="loom-message-content">
          <div class="loom-chat-log-spinner">
            <span></span><span></span><span></span>
          </div>
        </div>
      `;
      log.appendChild(loadingDiv);
      this.scrollToBottom();

      // 4. Send API query
      const currentFile = this.getCurrentlyViewedFilePath();
      chrome.runtime.sendMessage({
        type: 'API_REQUEST',
        method: 'POST',
        path: '/ask',
        body: {
          repo_id: activeRepoId,
          question: question,
          conversation_id: activeConversationId,
          current_file: currentFile
        }
      }, (response) => {
        // Remove loading indicator
        loadingDiv.remove();

        if (response && response.success && response.result && response.result.ok) {
          const data = response.result.data;
          activeConversationId = data.conversation_id;

          // Render assistant reply
          const replyDiv = document.createElement('div');
          replyDiv.className = 'loom-chat-row loom-chat-row-assistant';
          
          let citationsHtml = '';
          if (data.sources && data.sources.length > 0) {
            citationsHtml += '<div class="loom-citations">';
            data.sources.forEach(src => {
              // Build GitHub file URL
              const fileUrl = `https://github.com/${currentRepoName}/blob/main/${src.file}#L${src.line_start}`;
              citationsHtml += `
                <a href="${fileUrl}" target="_blank" class="loom-citation-chip" title="${src.file} (lines ${src.line_start}-${src.line_end})">
                  📄 ${src.file.split('/').pop()}:${src.line_start}
                </a>
              `;
            });
            citationsHtml += '</div>';
          }

          replyDiv.innerHTML = `
            <div class="loom-pfp-placeholder"></div>
            <div class="loom-message-content">
              ${this.formatAnswerText(data.answer)}
              ${citationsHtml}
            </div>
          `;
          log.appendChild(replyDiv);
        } else {
          // Render error bubble
          const errorDiv = document.createElement('div');
          errorDiv.className = 'loom-chat-row loom-chat-row-assistant';
          
          const errorMsg = (response && response.result && response.result.data && response.result.data.error)
            ? response.result.data.error
            : "Sorry, I had trouble contacting the Loom backend. Ensure Uvicorn server is running locally.";

          errorDiv.innerHTML = `
            <div class="loom-pfp-placeholder"></div>
            <div class="loom-message-content" style="color: #cf222e; border-color: rgba(207, 34, 46, 0.2); background: rgba(207, 34, 46, 0.05);">
              ⚠️ <strong>Error:</strong> ${errorMsg}
            </div>
          `;
          log.appendChild(errorDiv);
        }
        
        this.scrollToBottom();
      });
    }
  };

  // Export globally to window
  window.LoomQA = QA;
})();
