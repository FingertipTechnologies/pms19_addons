/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

/**
 * FT Helpdesk Portal JavaScript
 * Handles dynamic form interactions on the ticket creation page.
 */
function _initPortal() {

    // =============================
    // Category -> Subcategory
    // =============================
    const categorySelect = document.getElementById('category_id');
    const subcategoryWrapper = document.getElementById('subcategory_wrapper');
    const subcategorySelect = document.getElementById('subcategory_id');

    if (categorySelect) {
        categorySelect.addEventListener('change', async function () {
            const categoryId = this.value;
            if (!categoryId) {
                if (subcategoryWrapper) subcategoryWrapper.style.display = 'none';
                return;
            }
            try {
                const response = await fetch('/my/support/subcategories', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: { category_id: parseInt(categoryId) },
                    }),
                });
                const data = await response.json();
                const subcategories = data.result || [];

                if (subcategories.length > 0) {
                    subcategorySelect.innerHTML = '<option value="">-- Select Subcategory --</option>';
                    subcategories.forEach(function (sub) {
                        const opt = document.createElement('option');
                        opt.value = sub.id;
                        opt.textContent = sub.name;
                        subcategorySelect.appendChild(opt);
                    });
                    subcategoryWrapper.style.display = '';
                } else {
                    subcategoryWrapper.style.display = 'none';
                }
            } catch (e) {
                console.error('Error fetching subcategories:', e);
            }
        });
    }

    // =============================
    // Type -> Dynamic Fields
    // =============================
    const typeSelect = document.getElementById('type_id');
    const dynamicContainer = document.getElementById('dynamic_fields_container');
    const dynamicBody = document.getElementById('dynamic_fields_body');

    if (typeSelect) {
        typeSelect.addEventListener('change', async function () {
            const typeId = this.value;
            if (!typeId) {
                if (dynamicContainer) dynamicContainer.style.display = 'none';
                return;
            }
            try {
                const response = await fetch('/my/support/dynamic_fields', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: { type_id: parseInt(typeId) },
                    }),
                });
                const data = await response.json();
                const fields = data.result || [];

                if (fields.length > 0) {
                    dynamicBody.innerHTML = '';
                    fields.forEach(function (field) {
                        const col = document.createElement('div');
                        col.className = 'col-md-6 mb-3';
                        let inputHtml = '';
                        const fieldName = 'dynamic_' + field.name;
                        const required = field.required ? 'required' : '';

                        switch (field.type) {
                            case 'text':
                                inputHtml = `<textarea name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder}" rows="3" ${required}></textarea>`;
                                break;
                            case 'boolean':
                                inputHtml = `<div class="form-check mt-2">
                                    <input type="checkbox" name="${fieldName}" class="form-check-input"
                                        id="field_${field.name}" value="1">
                                    <label class="form-check-label" for="field_${field.name}">${field.label}</label>
                                </div>`;
                                break;
                            case 'selection':
                                let options = '<option value="">-- Select --</option>';
                                (field.options || []).forEach(function (opt) {
                                    options += `<option value="${opt}">${opt}</option>`;
                                });
                                inputHtml = `<select name="${fieldName}" class="form-select" ${required}>
                                    ${options}</select>`;
                                break;
                            case 'date':
                                inputHtml = `<input type="date" name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder}" ${required}>`;
                                break;
                            case 'datetime':
                                inputHtml = `<input type="datetime-local" name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder}" ${required}>`;
                                break;
                            case 'integer':
                                inputHtml = `<input type="number" name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder}" step="1" ${required}>`;
                                break;
                            case 'float':
                                inputHtml = `<input type="number" name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder}" step="0.01" ${required}>`;
                                break;
                            case 'url':
                                inputHtml = `<input type="url" name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder || 'https://...'}" ${required}>`;
                                break;
                            case 'email':
                                inputHtml = `<input type="email" name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder || 'email@example.com'}" ${required}>`;
                                break;
                            default:
                                inputHtml = `<input type="text" name="${fieldName}" class="form-control"
                                    placeholder="${field.placeholder}" ${required}>`;
                        }

                        const label = field.type !== 'boolean'
                            ? `<label class="form-label fw-medium">
                                ${field.label}${field.required ? ' <span class="text-danger">*</span>' : ''}
                               </label>`
                            : '';
                        const helpText = field.help_text
                            ? `<div class="form-text">${field.help_text}</div>`
                            : '';

                        col.innerHTML = label + inputHtml + helpText;
                        dynamicBody.appendChild(col);
                    });
                    dynamicContainer.style.display = '';
                } else {
                    dynamicContainer.style.display = 'none';
                }
            } catch (e) {
                console.error('Error fetching dynamic fields:', e);
            }
        });
    }

    // =============================
    // KB Suggestions (on subject input)
    // =============================
    const subjectInput = document.getElementById('ticket_subject');
    const kbSuggestions = document.getElementById('kb_suggestions');
    const kbSuggestionsList = document.getElementById('kb_suggestions_list');
    let suggestTimeout = null;

    if (subjectInput && kbSuggestions) {
        subjectInput.addEventListener('input', function () {
            clearTimeout(suggestTimeout);
            const query = this.value.trim();
            if (query.length < 3) {
                kbSuggestions.style.display = 'none';
                return;
            }
            suggestTimeout = setTimeout(async function () {
                try {
                    const catId = categorySelect ? categorySelect.value : '';
                    let url = `/my/support/kb/suggest?q=${encodeURIComponent(query)}`;
                    if (catId) url += `&category_id=${catId}`;

                    const response = await fetch(url);
                    if (!response.ok) {
                        kbSuggestions.style.display = 'none';
                        return;
                    }
                    const articles = await response.json();

                    if (articles && articles.length > 0) {
                        kbSuggestionsList.innerHTML = '';
                        articles.forEach(function (article) {
                            const link = document.createElement('a');
                            link.href = `/my/support/kb/${article.slug}`;
                            link.target = '_blank';
                            link.className = 'kb-suggestion-item';
                            link.innerHTML = `<i class="fa fa-file-text-o me-2"></i>${article.title}`;
                            kbSuggestionsList.appendChild(link);
                        });
                        kbSuggestions.style.display = '';
                    } else {
                        kbSuggestions.style.display = 'none';
                    }
                } catch (e) {
                    kbSuggestions.style.display = 'none';
                }
            }, 500);
        });
    }

    // =============================
    // Reply Attachment Preview
    // =============================
    _initReplyAttachmentPreview();

    // =============================
    // AJAX Tab Switching
    // =============================
    _initTabSwitching();
}

function _initReplyAttachmentPreview() {
    const input = document.getElementById('ft_reply_attachments_input');
    const preview = document.getElementById('ft_reply_attachments_preview');
    if (!input || !preview) return;

    let files = [];

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    function render() {
        preview.innerHTML = '';
        files.forEach(function (file, idx) {
            const chip = document.createElement('div');
            chip.className = 'ft-attachment-chip d-inline-flex align-items-center border rounded px-2 py-1 bg-light';
            chip.style.maxWidth = '260px';

            const icon = document.createElement('i');
            icon.className = 'fa me-2 text-muted';
            if (file.type.startsWith('image/')) {
                icon.classList.add('fa-image');
            } else if (file.type.startsWith('video/')) {
                icon.classList.add('fa-film');
            } else if (file.type === 'application/pdf') {
                icon.classList.add('fa-file-pdf-o');
            } else {
                icon.classList.add('fa-file-o');
            }

            const label = document.createElement('span');
            label.className = 'text-truncate small';
            label.style.maxWidth = '180px';
            label.textContent = file.name;
            label.title = file.name + ' (' + formatSize(file.size) + ')';

            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn btn-sm btn-link text-danger p-0 ms-2';
            remove.innerHTML = '<i class="fa fa-times"/>';
            remove.setAttribute('aria-label', 'Remove');
            remove.addEventListener('click', function () {
                files.splice(idx, 1);
                syncInput();
                render();
            });

            chip.appendChild(icon);
            chip.appendChild(label);
            chip.appendChild(remove);
            preview.appendChild(chip);
        });
    }

    function syncInput() {
        const dt = new DataTransfer();
        files.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
    }

    input.addEventListener('change', function () {
        const incoming = Array.from(input.files || []);
        incoming.forEach(function (f) {
            const exists = files.some(function (x) {
                return x.name === f.name && x.size === f.size && x.lastModified === f.lastModified;
            });
            if (!exists) files.push(f);
        });
        syncInput();
        render();
    });
}

// Ensure init runs whether DOMContentLoaded already fired or not
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initPortal);
} else {
    _initPortal();
}

// =============================
// AJAX Tab Switching (standalone — no publicWidget dependency)
// =============================
const TAB_URLS = [
    '/my/support/projects',
    '/my/support/tickets',
    '/my/support/milestones',
    '/my/support/releases',
    '/my/support/kb',
];

function isTabPageLink(href) {
    if (!href) return false;
    try {
        var path = new URL(href, window.location.origin).pathname;
        return TAB_URLS.some(function (t) {
            return path === t || path.startsWith(t + '?');
        });
    } catch (_e) {
        return false;
    }
}

function _initTabSwitching() {
    var portalEl = document.querySelector('.ft-support-portal');
    if (!portalEl) return;

    var tabContainer = portalEl.querySelector('.ft-support-tabs');
    var contentContainer = portalEl.querySelector('.ft-tab-content');
    if (!tabContainer || !contentContainer) return;

    var isLoading = false;

    function setActiveTab(url) {
        var path;
        try { path = new URL(url, window.location.origin).pathname; } catch (_e) { return; }
        tabContainer.querySelectorAll('.nav-link').forEach(function (link) {
            var linkHref = link.getAttribute('href');
            if (linkHref && path.startsWith(linkHref.split('?')[0])) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    }

    function attachContentListeners() {
        // Intercept filter/sort/pagination links inside tab content
        contentContainer.querySelectorAll('a').forEach(function (link) {
            var href = link.getAttribute('href');
            if (href && isTabPageLink(href) && !link.dataset.ftAjax) {
                link.dataset.ftAjax = '1';
                link.addEventListener('click', function (e) {
                    e.preventDefault();
                    loadContent(href, true);
                });
            }
        });
        // Intercept search forms inside tab content
        contentContainer.querySelectorAll('form').forEach(function (form) {
            var action = form.getAttribute('action');
            if (action && isTabPageLink(action) && !form.dataset.ftAjax) {
                form.dataset.ftAjax = '1';
                form.addEventListener('submit', function (e) {
                    e.preventDefault();
                    var formData = new FormData(form);
                    var params = new URLSearchParams(formData).toString();
                    var url = action + (params ? '?' + params : '');
                    loadContent(url, true);
                });
            }
        });
    }

    async function loadContent(url, doPushState) {
        if (isLoading) return;
        isLoading = true;
        contentContainer.style.opacity = '0.5';
        contentContainer.style.pointerEvents = 'none';
        try {
            var response = await fetch(url, { credentials: 'same-origin' });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            var html = await response.text();
            var parser = new DOMParser();
            var doc = parser.parseFromString(html, 'text/html');
            var newContent = doc.querySelector('.ft-tab-content');
            if (!newContent) throw new Error('No .ft-tab-content found in response');
            contentContainer.innerHTML = newContent.innerHTML;
            setActiveTab(url);
            if (doPushState) {
                history.pushState({ ftAjax: true, url: url }, '', url);
            }
            attachContentListeners();
        } catch (err) {
            console.warn('[FtSupportTabs] AJAX failed, full reload:', err);
            window.location.href = url;
        } finally {
            contentContainer.style.opacity = '';
            contentContainer.style.pointerEvents = '';
            isLoading = false;
        }
    }

    // Attach click handlers to tab links
    tabContainer.querySelectorAll('.nav-link').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            loadContent(this.getAttribute('href'), true);
        });
    });

    // Attach handlers to filter/sort links already in content
    attachContentListeners();

    // Handle browser back/forward
    history.replaceState({ ftAjax: true, url: window.location.href }, '', window.location.href);
    window.addEventListener('popstate', function (e) {
        if (e.state && e.state.ftAjax && e.state.url) {
            loadContent(e.state.url, false);
        }
    });
}
