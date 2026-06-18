<script lang="ts">
	import { streamChat, postChat, type ChatResponse, type SourceDocument } from '$lib/api';

	// ── Types ──────────────────────────────────────────────────────────────
	type Role = 'user' | 'assistant';
	type Lang = 'cs' | 'en';

	interface Message {
		id: string;
		role: Role;
		content: string;
		sources: SourceDocument[];
		route?: string;
		cached?: boolean;
		streaming?: boolean;
	}

	// ── i18n ───────────────────────────────────────────────────────────────
	const T = {
		cs: {
			appName: 'DocRAG',
			appTagline: 'Asistent pro AI dokumentaci',
			newChat: 'Nová konverzace',
			send: 'Odeslat',
			sending: 'Generuji…',
			placeholder: 'Zeptejte se na instalaci, konfiguraci, API, nebo troubleshooting…',
			enterHint: '⏎ Enter pro odeslání · Shift+Enter nový řádek',
			sourcesLabel: 'Zdroje',
			sourcesCollapse: 'Skrýt',
			sourcesExpand: 'Zobrazit',
			cached: 'z cache',
			emptyHeading: 'Čím mohu pomoci?',
			emptySubtitle: 'Ptejte se na dokumentaci AI coding nástrojů.',
			tools: 'Podporované nástroje',
			examples: 'Příklady dotazů',
			streamingLabel: 'Generuji odpověď…',
			errorPrefix: 'Chyba',
		},
		en: {
			appName: 'DocRAG',
			appTagline: 'AI Documentation Assistant',
			newChat: 'New conversation',
			send: 'Send',
			sending: 'Generating…',
			placeholder: 'Ask about installation, configuration, APIs, or troubleshooting…',
			enterHint: '⏎ Enter to send · Shift+Enter new line',
			sourcesLabel: 'Sources',
			sourcesCollapse: 'Collapse',
			sourcesExpand: 'Expand',
			cached: 'cached',
			emptyHeading: 'How can I help?',
			emptySubtitle: 'Ask about AI coding tool documentation.',
			tools: 'Supported tools',
			examples: 'Example questions',
			streamingLabel: 'Generating answer…',
			errorPrefix: 'Error',
		}
	} as const;

	// ── State ──────────────────────────────────────────────────────────────
	const storedLang = (typeof localStorage !== 'undefined' ? localStorage.getItem('docrag-lang') : null) ?? 'cs';
	let lang = $state<Lang>(storedLang === 'en' ? 'en' : 'cs');
	let t = $derived(T[lang]);

	let sessionId = $state('');
	let query = $state('');
	let messages = $state<Message[]>([]);
	let isLoading = $state(false);
	let errorMessage = $state('');
	let currentAssistantId = $state('');
	let expandedSources = $state(new Set<string>());
	let messagesEl: HTMLElement | undefined = $state();
	let textareaEl: HTMLTextAreaElement | undefined = $state();

	const EXAMPLE_QUESTIONS = {
		cs: [
			'Jak nainstaluji Claude Code?',
			'Jaký je rozdíl mezi Cursorem a Claude Code?',
			'Jak nakonfiguruji MCP servery v OpenCode?',
			'Které modely Hermes podporují function calling?',
		],
		en: [
			'How do I install Claude Code?',
			'What\'s the difference between Cursor and Claude Code?',
			'How do I configure MCP servers in OpenCode?',
			'Which Hermes models support function calling?',
		]
	};

	const TOOLS = [
		{ id: 'claude-code', name: 'Claude Code', icon: '◆', color: '#f97316' },
		{ id: 'cursor', name: 'Cursor', icon: '⚡', color: '#22c55e' },
		{ id: 'opencode', name: 'Opencode', icon: '{ }', color: '#60a5fa' },
		{ id: 'codex', name: 'Codex CLI', icon: '★', color: '#10b981' },
		{ id: 'hermes', name: 'Hermes', icon: '∞', color: '#f59e0b' },
		{ id: 'openclaw', name: 'OpenClaw', icon: '◈', color: '#e879f9' },
	];

	// ── Helpers ────────────────────────────────────────────────────────────
	function genId(): string {
		if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
		return 'id-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
	}

	function toggleLang() {
		lang = lang === 'cs' ? 'en' : 'cs';
		if (typeof localStorage !== 'undefined') localStorage.setItem('docrag-lang', lang);
	}

	function newConversation() {
		messages = [];
		sessionId = '';
		errorMessage = '';
		query = '';
		textareaEl?.focus();
	}

	function toggleSources(id: string) {
		const next = new Set(expandedSources);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expandedSources = next;
	}

	function useExample(q: string) {
		query = q;
		textareaEl?.focus();
	}

	function scrollToBottom() {
		if (messagesEl) {
			messagesEl.scrollTop = messagesEl.scrollHeight;
		}
	}

	$effect(() => {
		// Scroll whenever messages or content changes
		messages;
		setTimeout(scrollToBottom, 20);
	});

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			void sendMessage();
		}
	}

	// ── Route badge meta ───────────────────────────────────────────────────
	type RouteMeta = { label: string; color: string; bg: string };
	function routeMeta(route: string): RouteMeta {
		const map: Record<string, RouteMeta> = {
			docs_rag:           { label: 'docs',        color: '#a78bfa', bg: 'rgba(124,58,237,0.15)' },
			web_search:         { label: 'web',         color: '#22d3ee', bg: 'rgba(6,182,212,0.12)' },
			fallback_no_answer: { label: 'no answer',   color: '#f87171', bg: 'rgba(239,68,68,0.12)' },
			unsupported_direct: { label: 'hors scope',  color: '#94a3b8', bg: 'rgba(148,163,184,0.10)' },
			generic_llm:        { label: 'llm',         color: '#818cf8', bg: 'rgba(99,102,241,0.12)' },
			comparison_direct:  { label: 'comparison',  color: '#34d399', bg: 'rgba(52,211,153,0.12)' },
			identity_direct:    { label: 'identity',    color: '#94a3b8', bg: 'rgba(148,163,184,0.10)' },
			clarification_direct: { label: 'clarify',  color: '#94a3b8', bg: 'rgba(148,163,184,0.10)' },
			soft_guidance_direct: { label: 'guidance',  color: '#94a3b8', bg: 'rgba(148,163,184,0.10)' },
		};
		return map[route] ?? { label: route, color: '#94a3b8', bg: 'rgba(148,163,184,0.10)' };
	}

	// ── Provider color ─────────────────────────────────────────────────────
	function providerColor(provider: string): string {
		const map: Record<string, string> = {
			anthropic: '#f97316',
			cursor: '#22c55e',
			opencode: '#60a5fa',
			openai: '#10b981',
			hermes: '#f59e0b',
			openclaw: '#e879f9',
			web: '#22d3ee',
		};
		return map[provider] ?? '#a78bfa';
	}

	// ── Minimal Markdown renderer ──────────────────────────────────────────
	function renderMarkdown(raw: string): string {
		if (!raw) return '';

		// 1. Extract and protect fenced code blocks
		const codeBlocks: string[] = [];
		let text = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
			const i = codeBlocks.length;
			const escaped = code.trim().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
			codeBlocks.push(
				`<pre class="md-pre"><code class="md-code-block${lang ? ' lang-'+lang : ''}">${escaped}</code></pre>`
			);
			return `\x00CB${i}\x00`;
		});

		// 2. Inline code
		text = text.replace(/`([^`\n]+)`/g, (_, c) =>
			`<code class="md-inline">${c.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</code>`
		);

		// 3. Bold + italic
		text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
		text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
		text = text.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

		// 4. Links [label](url)
		text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
			'<a href="$2" target="_blank" rel="noreferrer" class="md-link">$1</a>'
		);

		// 5. Headings (line-start only)
		text = text.replace(/^#{4,} (.+)$/gm, '<h5 class="md-h5">$1</h5>');
		text = text.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
		text = text.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');
		text = text.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>');

		// 6. Blockquotes
		text = text.replace(/^> (.+)$/gm, '<blockquote class="md-blockquote">$1</blockquote>');

		// 7. Horizontal rules
		text = text.replace(/^---+$/gm, '<hr class="md-hr">');

		// 8. Unordered lists — collect consecutive list lines
		text = text.replace(/((?:^[ \t]*[-*+] .+\n?)+)/gm, (block) => {
			const items = block.trim().split('\n').map(l =>
				`<li>${l.replace(/^[ \t]*[-*+] /, '')}</li>`
			).join('');
			return `<ul class="md-ul">${items}</ul>`;
		});

		// 9. Ordered lists
		text = text.replace(/((?:^[ \t]*\d+\. .+\n?)+)/gm, (block) => {
			const items = block.trim().split('\n').map(l =>
				`<li>${l.replace(/^[ \t]*\d+\. /, '')}</li>`
			).join('');
			return `<ol class="md-ol">${items}</ol>`;
		});

		// 10. Tables — detect blocks of pipe-delimited lines with a separator row
		text = text.replace(/((?:^\|.+\|\s*\n?)+)/gm, (block) => {
			const lines = block.trim().split('\n').map(l => l.trim()).filter(Boolean);
			if (lines.length < 2) return block;
			// Separator row: cells contain only dashes, colons, spaces
			const isSep = (l: string) => /^\|[\s\-:|]+\|$/.test(l);
			const sepIdx = lines.findIndex(isSep);
			if (sepIdx !== 1) return block; // separator must be second line
			const parseRow = (l: string) =>
				l.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
			const headers = parseRow(lines[0]);
			const thead = `<thead class="md-thead"><tr>${
				headers.map(h => `<th class="md-th">${h}</th>`).join('')
			}</tr></thead>`;
			const tbody = lines.slice(2).map(row =>
				`<tr>${parseRow(row).map(c => `<td class="md-td">${c}</td>`).join('')}</tr>`
			).join('');
			return `<table class="md-table">${thead}<tbody>${tbody}</tbody></table>`;
		});

		// 11. Paragraphs — split on blank lines
		const blocks = text.split(/\n{2,}/);
		text = blocks.map(b => {
			b = b.trim();
			if (!b) return '';
			// Don't wrap block elements in <p>
			if (/^<(h[2-5]|ul|ol|pre|blockquote|hr|table)/.test(b)) return b;
			if (/^\x00CB\d+\x00$/.test(b)) return b;
			// Single newlines within paragraph → <br>
			return `<p class="md-p">${b.replace(/\n/g, '<br>')}</p>`;
		}).join('\n');

		// 11. Restore code blocks
		text = text.replace(/\x00CB(\d+)\x00/g, (_, i) => codeBlocks[parseInt(i)]);

		return text;
	}

	// ── Message helpers ────────────────────────────────────────────────────
	function appendToken(id: string, token: string) {
		messages = messages.map(m => m.id === id ? { ...m, content: m.content + token } : m);
	}

	function patchMessage(id: string, patch: Partial<Message>) {
		messages = messages.map(m => m.id === id ? { ...m, ...patch } : m);
	}

	function applyFinal(id: string, response: ChatResponse) {
		messages = messages.map(m =>
			m.id === id ? {
				...m,
				content: response.answer,
				sources: response.sources,
				route: response.route,
				cached: response.cached,
				streaming: false,
			} : m
		);
	}

	// ── Send ───────────────────────────────────────────────────────────────
	async function sendMessage() {
		const trimmed = query.trim();
		if (!trimmed || isLoading) return;

		errorMessage = '';
		isLoading = true;

		messages = [...messages, {
			id: genId(), role: 'user', content: trimmed, sources: []
		}];

		const assistantId = genId();
		currentAssistantId = assistantId;
		messages = [...messages, {
			id: assistantId, role: 'assistant', content: '', sources: [], streaming: true
		}];

		const currentQuery = trimmed;
		query = '';

		try {
			await streamChat(
				{ query: currentQuery, session_id: sessionId || undefined },
				{
					onEvent: (event) => {
						if (event.type === 'session') sessionId = event.session_id;
						if (event.type === 'meta') {
							patchMessage(assistantId, {
								route: event.route,
								cached: event.cached,
								sources: event.sources,
							});
						}
						if (event.type === 'error') errorMessage = event.detail;
					},
					onToken: (token) => appendToken(assistantId, token),
					onDone: (response) => {
						applyFinal(assistantId, response);
						sessionId = response.session_id || sessionId;
					},
					onError: async (message) => {
						if (!message) {
							try {
								const fallback = await postChat({ query: currentQuery, session_id: sessionId || undefined });
								applyFinal(assistantId, fallback);
								sessionId = fallback.session_id;
								return;
							} catch (err) {
								message = err instanceof Error ? err.message : 'Request failed.';
							}
						}
						errorMessage = message;
						patchMessage(assistantId, { streaming: false, content: messages.find(m => m.id === assistantId)?.content || 'Unable to complete the request.' });
					}
				}
			);
		} catch (err) {
			errorMessage = err instanceof Error ? err.message : 'Request failed.';
			patchMessage(assistantId, { streaming: false });
		} finally {
			currentAssistantId = '';
			isLoading = false;
		}
	}
</script>

<svelte:head>
	<title>DocRAG — AI Documentation Assistant</title>
	<meta name="description" content="AI documentation assistant for Claude Code, Cursor, Opencode, Codex, Hermes, and OpenClaw." />
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
</svelte:head>

<!-- ── Root ───────────────────────────────────────────────────────────── -->
<div class="root">

	<!-- Ambient glow blobs -->
	<div class="bg-blob blob-1" aria-hidden="true"></div>
	<div class="bg-blob blob-2" aria-hidden="true"></div>

	<!-- ── Header ──────────────────────────────────────────────────────── -->
	<header class="header">
		<div class="logo">
			<span class="logo-mark" aria-hidden="true">◆</span>
			<div class="logo-text">
				<span class="logo-name">{t.appName}</span>
				<span class="logo-tag">{t.appTagline}</span>
			</div>
		</div>
		<div class="header-actions">
			<button class="lang-toggle" onclick={toggleLang} title="Switch language">
				{lang === 'cs' ? 'EN' : 'CZ'}
			</button>
			<button class="new-chat-btn" onclick={newConversation}>
				<span aria-hidden="true">＋</span>
				{t.newChat}
			</button>
		</div>
	</header>

	<!-- ── Messages ────────────────────────────────────────────────────── -->
	<main class="messages-wrap" bind:this={messagesEl} aria-live="polite" aria-label="Conversation">

		{#if messages.length === 0}
			<!-- ── Empty state ─────────────────────────────────────────── -->
			<div class="empty-state">
				<div class="empty-hero">
					<div class="empty-logo-ring" aria-hidden="true">
						<span class="empty-logo-inner">◆</span>
					</div>
					<h1 class="empty-heading">{t.emptyHeading}</h1>
					<p class="empty-sub">{t.emptySubtitle}</p>
				</div>

				<div class="tools-section">
					<p class="section-label">{t.tools}</p>
					<div class="tools-grid">
						{#each TOOLS as tool}
							<div class="tool-card">
								<span class="tool-icon" style="color: {tool.color}; text-shadow: 0 0 12px {tool.color}55">{tool.icon}</span>
								<span class="tool-name">{tool.name}</span>
							</div>
						{/each}
					</div>
				</div>

				<div class="examples-section">
					<p class="section-label">{t.examples}</p>
					<div class="examples-grid">
						{#each EXAMPLE_QUESTIONS[lang] as ex}
							<button class="example-chip" onclick={() => useExample(ex)}>
								{ex}
							</button>
						{/each}
					</div>
				</div>
			</div>
		{/if}

		{#each messages as msg (msg.id)}
			<article class="message message-{msg.role}">

				{#if msg.role === 'user'}
					<!-- ── User bubble ──────────────────────────────────── -->
					<div class="user-bubble">
						<p class="user-text">{msg.content}</p>
					</div>

				{:else}
					<!-- ── Assistant panel ─────────────────────────────── -->
					<div class="assistant-panel" class:streaming={msg.streaming}>

						<!-- Meta row -->
						<div class="msg-meta">
							{#if msg.route}
								{@const rm = routeMeta(msg.route)}
								<span class="route-badge" style="color:{rm.color};background:{rm.bg};border-color:{rm.color}33">
									{rm.label}
								</span>
							{/if}
							{#if msg.cached}
								<span class="cached-badge">{t.cached}</span>
							{/if}
						</div>

						<!-- Content -->
						<div class="assistant-content">
							{#if msg.streaming && !msg.content}
								<div class="typing-dots" aria-label={t.streamingLabel}>
									<span></span><span></span><span></span>
								</div>
							{:else if msg.content}
									<div class="md-body">{@html renderMarkdown(msg.content)}</div>
							{/if}
						</div>

						<!-- Sources -->
						{#if msg.sources.length > 0}
							<div class="sources-section">
								<button
									class="sources-toggle"
									onclick={() => toggleSources(msg.id)}
									aria-expanded={expandedSources.has(msg.id)}
								>
									<span class="sources-count">{msg.sources.length}</span>
									{t.sourcesLabel}
									<span class="sources-chevron" class:open={expandedSources.has(msg.id)}>›</span>
								</button>

								{#if expandedSources.has(msg.id)}
									<div class="sources-list">
										{#each msg.sources as src}
											<a
												href={src.url}
												target="_blank"
												rel="noreferrer"
												class="source-card"
											>
												<span
													class="src-provider-dot"
													style="background:{providerColor(src.provider)};box-shadow:0 0 6px {providerColor(src.provider)}66"
												></span>
												<div class="src-info">
													<span class="src-title">{src.title}</span>
													<span class="src-url">{src.url}</span>
												</div>
												{#if src.doc_type}
													<span class="src-type">{src.doc_type}</span>
												{/if}
											</a>
										{/each}
									</div>
								{/if}
							</div>
						{/if}

					</div>
				{/if}

			</article>
		{/each}

	</main>

	<!-- ── Error ───────────────────────────────────────────────────────── -->
	{#if errorMessage}
		<div class="error-bar" role="alert">
			<span class="error-icon" aria-hidden="true">⚠</span>
			{t.errorPrefix}: {errorMessage}
			<button class="error-close" onclick={() => errorMessage = ''} aria-label="Dismiss">✕</button>
		</div>
	{/if}

	<!-- ── Composer ─────────────────────────────────────────────────────── -->
	<footer class="composer">
		<div class="composer-inner">
			<label class="sr-only" for="query-input">Ask a documentation question</label>
			<textarea
				id="query-input"
				bind:this={textareaEl}
				bind:value={query}
				onkeydown={handleKeydown}
				placeholder={t.placeholder}
				disabled={isLoading}
				rows={3}
			></textarea>
			<div class="composer-footer">
				<span class="composer-hint">{t.enterHint}</span>
				<button
					class="send-btn"
					onclick={() => void sendMessage()}
					disabled={isLoading || !query.trim()}
					aria-label={t.send}
				>
					{#if isLoading}
						<span class="send-spinner" aria-hidden="true"></span>
						{t.sending}
					{:else}
						<span class="send-arrow" aria-hidden="true">↑</span>
						{t.send}
					{/if}
				</button>
			</div>
		</div>
	</footer>

</div>

<style>
	/* ── Reset / globals ─────────────────────────────────────────────────── */
	:global(html), :global(body) {
		margin: 0;
		padding: 0;
		min-height: 100%;
		background: #0a0a0f;
		color: #e8e8f0;
		font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
		font-size: 15px;
		line-height: 1.6;
		-webkit-font-smoothing: antialiased;
	}

	:global(*), :global(*::before), :global(*::after) {
		box-sizing: border-box;
	}

	/* ── Root layout ─────────────────────────────────────────────────────── */
	.root {
		display: grid;
		grid-template-rows: auto 1fr auto auto;
		height: 100dvh;
		max-width: 900px;
		margin: 0 auto;
		position: relative;
	}

	/* ── Ambient background blobs ────────────────────────────────────────── */
	.bg-blob {
		position: fixed;
		border-radius: 50%;
		filter: blur(100px);
		pointer-events: none;
		z-index: -1;
		opacity: 0.35;
	}
	.blob-1 {
		width: 600px;
		height: 600px;
		background: radial-gradient(circle, #7c3aed 0%, transparent 70%);
		top: -200px;
		right: -200px;
	}
	.blob-2 {
		width: 400px;
		height: 400px;
		background: radial-gradient(circle, #4c1d95 0%, transparent 70%);
		bottom: -100px;
		left: -150px;
	}

	/* ── Header ──────────────────────────────────────────────────────────── */
	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid rgba(124, 58, 237, 0.18);
		background: rgba(10, 10, 15, 0.8);
		backdrop-filter: blur(20px);
		position: sticky;
		top: 0;
		z-index: 10;
	}

	.logo {
		display: flex;
		align-items: center;
		gap: 0.65rem;
	}

	.logo-mark {
		font-size: 1.3rem;
		color: #8b5cf6;
		text-shadow: 0 0 20px #7c3aed99, 0 0 40px #7c3aed44;
		animation: pulse-glow 3s ease-in-out infinite;
	}

	.logo-text {
		display: flex;
		flex-direction: column;
		gap: 0.05rem;
	}

	.logo-name {
		font-size: 1rem;
		font-weight: 700;
		letter-spacing: -0.02em;
		color: #f0f0f8;
	}

	.logo-tag {
		font-size: 0.68rem;
		color: #7a7a96;
		letter-spacing: 0.02em;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.lang-toggle {
		background: rgba(124, 58, 237, 0.1);
		border: 1px solid rgba(124, 58, 237, 0.3);
		color: #a78bfa;
		border-radius: 999px;
		padding: 0.3rem 0.75rem;
		font: 600 0.75rem/1 'Inter', sans-serif;
		letter-spacing: 0.08em;
		cursor: pointer;
		transition: background 0.2s, color 0.2s, border-color 0.2s;
	}
	.lang-toggle:hover {
		background: rgba(124, 58, 237, 0.2);
		border-color: rgba(124, 58, 237, 0.5);
		color: #c4b5fd;
	}

	.new-chat-btn {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		background: linear-gradient(135deg, #7c3aed, #6d28d9);
		border: none;
		border-radius: 999px;
		padding: 0.4rem 0.9rem;
		color: #f0e6ff;
		font: 500 0.82rem/1 'Inter', sans-serif;
		cursor: pointer;
		box-shadow: 0 0 20px rgba(124, 58, 237, 0.3);
		transition: opacity 0.2s, transform 0.15s, box-shadow 0.2s;
	}
	.new-chat-btn:hover {
		opacity: 0.9;
		transform: translateY(-1px);
		box-shadow: 0 0 28px rgba(124, 58, 237, 0.45);
	}

	/* ── Messages container ──────────────────────────────────────────────── */
	.messages-wrap {
		overflow-y: auto;
		padding: 1.5rem 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		scrollbar-width: thin;
		scrollbar-color: rgba(124, 58, 237, 0.2) transparent;
	}
	.messages-wrap::-webkit-scrollbar {
		width: 4px;
	}
	.messages-wrap::-webkit-scrollbar-track {
		background: transparent;
	}
	.messages-wrap::-webkit-scrollbar-thumb {
		background: rgba(124, 58, 237, 0.25);
		border-radius: 99px;
	}

	/* ── Empty state ─────────────────────────────────────────────────────── */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2.5rem;
		padding: 2rem 0;
		text-align: center;
	}

	.empty-hero {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.85rem;
	}

	.empty-logo-ring {
		width: 72px;
		height: 72px;
		border-radius: 50%;
		border: 1px solid rgba(124, 58, 237, 0.3);
		background: radial-gradient(circle, rgba(124,58,237,0.15) 0%, transparent 70%);
		display: flex;
		align-items: center;
		justify-content: center;
		box-shadow: 0 0 40px rgba(124, 58, 237, 0.2), inset 0 0 20px rgba(124, 58, 237, 0.1);
		animation: pulse-ring 4s ease-in-out infinite;
	}

	.empty-logo-inner {
		font-size: 1.8rem;
		color: #8b5cf6;
		text-shadow: 0 0 20px #7c3aed88;
	}

	.empty-heading {
		margin: 0;
		font-size: 1.8rem;
		font-weight: 700;
		letter-spacing: -0.03em;
		background: linear-gradient(135deg, #f0f0f8 0%, #a78bfa 100%);
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
	}

	.empty-sub {
		margin: 0;
		color: #7a7a96;
		font-size: 0.92rem;
	}

	.section-label {
		margin: 0 0 0.75rem;
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: #5a5a75;
	}

	.tools-section, .examples-section {
		width: 100%;
		max-width: 600px;
	}

	.tools-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.6rem;
	}

	.tool-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.45rem;
		padding: 0.9rem 0.5rem;
		border-radius: 14px;
		border: 1px solid rgba(255,255,255,0.06);
		background: rgba(17, 17, 24, 0.6);
		backdrop-filter: blur(8px);
		transition: border-color 0.2s, background 0.2s;
	}
	.tool-card:hover {
		border-color: rgba(124, 58, 237, 0.25);
		background: rgba(26, 26, 36, 0.8);
	}

	.tool-icon {
		font-size: 1.35rem;
		line-height: 1;
	}

	.tool-name {
		font-size: 0.72rem;
		font-weight: 500;
		color: #9090aa;
		letter-spacing: 0.01em;
	}

	.examples-grid {
		display: grid;
		gap: 0.5rem;
	}

	.example-chip {
		background: rgba(17, 17, 24, 0.8);
		border: 1px solid rgba(255,255,255,0.07);
		border-radius: 10px;
		padding: 0.7rem 1rem;
		color: #b0b0c8;
		font: 400 0.85rem/1.4 'Inter', sans-serif;
		text-align: left;
		cursor: pointer;
		transition: border-color 0.2s, color 0.2s, background 0.2s;
	}
	.example-chip:hover {
		border-color: rgba(124, 58, 237, 0.35);
		color: #d0d0e8;
		background: rgba(26, 26, 36, 0.9);
	}

	/* ── Message layout ──────────────────────────────────────────────────── */
	.message {
		display: flex;
		flex-direction: column;
	}

	.message-user {
		align-items: flex-end;
	}

	.message-assistant {
		align-items: flex-start;
	}

	/* ── User bubble ─────────────────────────────────────────────────────── */
	.user-bubble {
		max-width: min(70%, 560px);
		padding: 0.85rem 1.1rem;
		border-radius: 20px 20px 4px 20px;
		background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 50%, #5b21b6 100%);
		box-shadow: 0 4px 24px rgba(124, 58, 237, 0.3), 0 1px 0 rgba(255,255,255,0.05) inset;
	}

	.user-text {
		margin: 0;
		color: #f0e8ff;
		font-size: 0.92rem;
		line-height: 1.55;
		white-space: pre-wrap;
		word-break: break-word;
	}

	/* ── Assistant panel ─────────────────────────────────────────────────── */
	.assistant-panel {
		max-width: min(90%, 720px);
		border-radius: 4px 20px 20px 20px;
		border: 1px solid rgba(124, 58, 237, 0.12);
		background: rgba(17, 17, 24, 0.85);
		backdrop-filter: blur(12px);
		overflow: hidden;
		transition: border-color 0.3s;
	}

	.assistant-panel.streaming {
		border-color: rgba(124, 58, 237, 0.3);
		box-shadow: 0 0 0 1px rgba(124, 58, 237, 0.1);
	}

	.msg-meta {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.6rem 1rem 0;
	}

	.route-badge {
		display: inline-flex;
		align-items: center;
		padding: 0.2rem 0.55rem;
		border-radius: 999px;
		border: 1px solid;
		font-size: 0.67rem;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.cached-badge {
		display: inline-flex;
		align-items: center;
		padding: 0.2rem 0.5rem;
		border-radius: 999px;
		background: rgba(148, 163, 184, 0.08);
		border: 1px solid rgba(148, 163, 184, 0.15);
		font-size: 0.67rem;
		font-weight: 500;
		color: #6a6a85;
		letter-spacing: 0.04em;
	}

	.assistant-content {
		padding: 0.75rem 1rem 1rem;
		min-height: 2.5rem;
	}

	/* ── Typing dots ─────────────────────────────────────────────────────── */
	.typing-dots {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 0.25rem 0;
	}

	.typing-dots span {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #7c3aed;
		animation: dot-bounce 1.4s ease-in-out infinite;
	}
	.typing-dots span:nth-child(2) { animation-delay: 0.16s; }
	.typing-dots span:nth-child(3) { animation-delay: 0.32s; }

	/* ── Markdown body ───────────────────────────────────────────────────── */
	.md-body {
		color: #d8d8ec;
		font-size: 0.9rem;
		line-height: 1.65;
		word-break: break-word;
	}

	:global(.md-body .md-p) {
		margin: 0 0 0.85em;
	}
	:global(.md-body .md-p:last-child) {
		margin-bottom: 0;
	}
	:global(.md-body .md-h2) {
		margin: 1.2em 0 0.5em;
		font-size: 1.1rem;
		font-weight: 700;
		color: #f0f0f8;
		letter-spacing: -0.02em;
	}
	:global(.md-body .md-h3) {
		margin: 1em 0 0.4em;
		font-size: 0.98rem;
		font-weight: 600;
		color: #e0e0f0;
	}
	:global(.md-body .md-h4), :global(.md-body .md-h5) {
		margin: 0.8em 0 0.35em;
		font-size: 0.9rem;
		font-weight: 600;
		color: #c8c8e0;
	}
	:global(.md-body .md-ul), :global(.md-body .md-ol) {
		margin: 0.5em 0 0.85em;
		padding-left: 1.4em;
	}
	:global(.md-body li) {
		margin-bottom: 0.3em;
	}
	:global(.md-body .md-link) {
		color: #a78bfa;
		text-decoration: none;
		border-bottom: 1px solid rgba(167, 139, 250, 0.3);
		transition: color 0.15s, border-color 0.15s;
	}
	:global(.md-body .md-link:hover) {
		color: #c4b5fd;
		border-color: rgba(196, 181, 253, 0.5);
	}
	:global(.md-body .md-inline) {
		padding: 0.1em 0.38em;
		border-radius: 5px;
		background: rgba(124, 58, 237, 0.12);
		border: 1px solid rgba(124, 58, 237, 0.18);
		color: #c4b5fd;
		font: 0.83em/1.4 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
	}
	:global(.md-body .md-pre) {
		margin: 0.75em 0;
		padding: 1rem;
		border-radius: 10px;
		background: rgba(8, 8, 14, 0.9);
		border: 1px solid rgba(124, 58, 237, 0.15);
		overflow-x: auto;
	}
	:global(.md-body .md-code-block) {
		font: 0.82em/1.55 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
		color: #c8c8e8;
		white-space: pre;
	}
	:global(.md-body .md-blockquote) {
		margin: 0.75em 0;
		padding: 0.5em 0.9em;
		border-left: 3px solid rgba(124, 58, 237, 0.5);
		background: rgba(124, 58, 237, 0.05);
		border-radius: 0 6px 6px 0;
		color: #a0a0bc;
		font-style: italic;
	}
	:global(.md-body .md-hr) {
		border: none;
		border-top: 1px solid rgba(255,255,255,0.07);
		margin: 1em 0;
	}
	:global(.md-body .md-table) {
		width: 100%;
		border-collapse: collapse;
		margin: 0.85em 0;
		font-size: 0.85rem;
		border: 1px solid rgba(124, 58, 237, 0.2);
		border-radius: 8px;
		overflow: hidden;
	}
	:global(.md-body .md-thead) {
		background: rgba(124, 58, 237, 0.15);
	}
	:global(.md-body .md-th) {
		padding: 0.55rem 0.85rem;
		text-align: left;
		font-weight: 600;
		color: #c4b5fd;
		border-bottom: 1px solid rgba(124, 58, 237, 0.25);
		white-space: nowrap;
	}
	:global(.md-body .md-td) {
		padding: 0.48rem 0.85rem;
		border-bottom: 1px solid rgba(255, 255, 255, 0.05);
		color: #c8c8e0;
		vertical-align: top;
	}
	:global(.md-body tbody tr:last-child .md-td) {
		border-bottom: none;
	}
	:global(.md-body tbody tr:hover) {
		background: rgba(124, 58, 237, 0.05);
	}

	/* ── Sources ─────────────────────────────────────────────────────────── */
	.sources-section {
		border-top: 1px solid rgba(255,255,255,0.05);
		padding: 0.6rem 1rem;
	}

	.sources-toggle {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		background: none;
		border: none;
		color: #6a6a88;
		font: 500 0.78rem/1 'Inter', sans-serif;
		cursor: pointer;
		padding: 0.2rem 0;
		transition: color 0.2s;
	}
	.sources-toggle:hover {
		color: #a78bfa;
	}

	.sources-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		background: rgba(124, 58, 237, 0.15);
		border: 1px solid rgba(124, 58, 237, 0.25);
		font-size: 0.68rem;
		font-weight: 700;
		color: #8b5cf6;
	}

	.sources-chevron {
		font-size: 1rem;
		line-height: 1;
		display: inline-block;
		transition: transform 0.2s;
		color: inherit;
	}
	.sources-chevron.open {
		transform: rotate(90deg);
	}

	.sources-list {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		margin-top: 0.6rem;
	}

	.source-card {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		padding: 0.6rem 0.8rem;
		border-radius: 10px;
		border: 1px solid rgba(255,255,255,0.05);
		background: rgba(8, 8, 14, 0.5);
		text-decoration: none;
		transition: border-color 0.2s, background 0.2s;
	}
	.source-card:hover {
		border-color: rgba(124, 58, 237, 0.25);
		background: rgba(17, 17, 26, 0.8);
	}

	.src-provider-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.src-info {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
		flex: 1;
	}

	.src-title {
		font-size: 0.82rem;
		font-weight: 500;
		color: #c0c0d8;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.src-url {
		font-size: 0.7rem;
		color: #5a5a75;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.src-type {
		flex-shrink: 0;
		font-size: 0.65rem;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: #5a5a75;
	}

	/* ── Error bar ───────────────────────────────────────────────────────── */
	.error-bar {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		margin: 0 1.25rem;
		padding: 0.75rem 1rem;
		border-radius: 12px;
		background: rgba(127, 29, 29, 0.3);
		border: 1px solid rgba(248, 113, 113, 0.25);
		color: #fca5a5;
		font-size: 0.85rem;
	}

	.error-icon {
		flex-shrink: 0;
		font-size: 0.9rem;
	}

	.error-close {
		margin-left: auto;
		background: none;
		border: none;
		color: #f87171;
		cursor: pointer;
		font-size: 0.85rem;
		padding: 0.1rem 0.25rem;
		border-radius: 4px;
		opacity: 0.7;
		transition: opacity 0.15s;
	}
	.error-close:hover {
		opacity: 1;
	}

	/* ── Composer ────────────────────────────────────────────────────────── */
	.composer {
		padding: 0.75rem 1.25rem 1rem;
		background: rgba(10, 10, 15, 0.8);
		backdrop-filter: blur(20px);
		border-top: 1px solid rgba(124, 58, 237, 0.12);
	}

	.composer-inner {
		border: 1px solid rgba(124, 58, 237, 0.2);
		border-radius: 16px;
		background: rgba(17, 17, 24, 0.9);
		overflow: hidden;
		transition: border-color 0.2s, box-shadow 0.2s;
	}
	.composer-inner:focus-within {
		border-color: rgba(124, 58, 237, 0.45);
		box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.08);
	}

	textarea {
		width: 100%;
		display: block;
		background: none;
		border: none;
		outline: none;
		resize: none;
		padding: 0.9rem 1rem 0.5rem;
		color: #e8e8f0;
		font: 400 0.9rem/1.55 'Inter', sans-serif;
		caret-color: #8b5cf6;
	}

	textarea::placeholder {
		color: #4a4a62;
	}

	textarea:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.composer-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.4rem 0.75rem 0.6rem;
	}

	.composer-hint {
		font-size: 0.7rem;
		color: #3a3a52;
		letter-spacing: 0.02em;
	}

	.send-btn {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		background: linear-gradient(135deg, #7c3aed, #6d28d9);
		border: none;
		border-radius: 999px;
		padding: 0.45rem 1rem;
		color: #f0e8ff;
		font: 600 0.82rem/1 'Inter', sans-serif;
		cursor: pointer;
		box-shadow: 0 2px 12px rgba(124, 58, 237, 0.35);
		transition: opacity 0.2s, transform 0.15s, box-shadow 0.2s;
	}
	.send-btn:hover:not(:disabled) {
		opacity: 0.92;
		transform: translateY(-1px);
		box-shadow: 0 4px 20px rgba(124, 58, 237, 0.5);
	}
	.send-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.send-arrow {
		font-size: 1rem;
		line-height: 1;
	}

	.send-spinner {
		width: 13px;
		height: 13px;
		border-radius: 50%;
		border: 2px solid rgba(240, 232, 255, 0.25);
		border-top-color: #f0e8ff;
		animation: spin 0.7s linear infinite;
		display: inline-block;
	}

	/* ── Animations ──────────────────────────────────────────────────────── */
	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	@keyframes dot-bounce {
		0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
		30% { transform: translateY(-6px); opacity: 1; }
	}

	@keyframes pulse-glow {
		0%, 100% { text-shadow: 0 0 20px #7c3aed88, 0 0 40px #7c3aed33; }
		50% { text-shadow: 0 0 28px #8b5cf6bb, 0 0 56px #7c3aed55; }
	}

	@keyframes pulse-ring {
		0%, 100% { box-shadow: 0 0 40px rgba(124,58,237,0.15), inset 0 0 20px rgba(124,58,237,0.08); }
		50% { box-shadow: 0 0 60px rgba(124,58,237,0.28), inset 0 0 30px rgba(124,58,237,0.14); }
	}

	/* ── Accessibility ───────────────────────────────────────────────────── */
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0,0,0,0);
		white-space: nowrap;
		border: 0;
	}

	/* ── Mobile ──────────────────────────────────────────────────────────── */
	@media (max-width: 600px) {
		.root {
			max-width: 100%;
		}

		.header {
			padding: 0.8rem 1rem;
		}

		.logo-tag {
			display: none;
		}

		.new-chat-btn {
			padding: 0.38rem 0.65rem;
			font-size: 0.76rem;
		}

		.messages-wrap {
			padding: 1rem;
		}

		.tools-grid {
			grid-template-columns: repeat(3, 1fr);
			gap: 0.45rem;
		}

		.tool-card {
			padding: 0.7rem 0.35rem;
		}

		.user-bubble {
			max-width: 85%;
		}

		.assistant-panel {
			max-width: 95%;
		}

		.composer {
			padding: 0.6rem 0.75rem 0.75rem;
		}

		.composer-hint {
			display: none;
		}
	}
</style>
