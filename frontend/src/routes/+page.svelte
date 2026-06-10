<script lang="ts">
	import { postChat, streamChat, type ChatResponse, type SourceDocument } from '$lib/api';

	type Role = 'user' | 'assistant';

	interface Message {
		id: string;
		role: Role;
		content: string;
		sources: SourceDocument[];
		route?: string;
		cached?: boolean;
	}

	let sessionId = '';
	let query = '';
	let messages: Message[] = [
		{
			id: crypto.randomUUID(),
			role: 'assistant',
			content:
				'Ask about Claude Code, Cursor, Opencode, Codex, Hermes, or OpenClaw. Responses stream in as they are generated.',
			sources: []
		}
	];
	let isLoading = false;
	let errorMessage = '';
	let currentAssistantId = '';

	async function sendMessage() {
		const trimmed = query.trim();
		if (!trimmed || isLoading) {
			return;
		}

		errorMessage = '';
		isLoading = true;

		const userMessage: Message = {
			id: crypto.randomUUID(),
			role: 'user',
			content: trimmed,
			sources: []
		};
		messages = [...messages, userMessage];

		const placeholderId = crypto.randomUUID();
		currentAssistantId = placeholderId;
		messages = [
			...messages,
			{
				id: placeholderId,
				role: 'assistant',
				content: '',
				sources: []
			}
		];

		const currentQuery = trimmed;
		query = '';

		try {
			await streamChat(
				{ query: currentQuery, session_id: sessionId || undefined },
				{
					onEvent: (event) => {
						if (event.type === 'session') {
							sessionId = event.session_id;
						}

						if (event.type === 'meta') {
							updateAssistantMessage(placeholderId, {
								route: event.route,
								cached: event.cached,
								sources: event.sources
							});
						}

						if (event.type === 'error') {
							errorMessage = event.detail;
						}
					},
					onToken: (token) => {
						appendAssistantToken(placeholderId, token);
					},
					onDone: (response) => {
						applyFinalAssistantResponse(placeholderId, response);
						sessionId = response.session_id || sessionId;
					},
					onError: async (message) => {
						if (!message) {
							try {
								const fallback = await postChat({
									query: currentQuery,
									session_id: sessionId || undefined
								});
								applyFinalAssistantResponse(placeholderId, fallback);
								sessionId = fallback.session_id;
								return;
							} catch (fallbackError) {
								message = fallbackError instanceof Error ? fallbackError.message : 'Request failed.';
							}
						}

						errorMessage = message;
						updateAssistantMessage(placeholderId, {
							content: messages.find((messageItem) => messageItem.id === placeholderId)?.content || 'Unable to complete the request.'
						});
					}
				}
			);
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : 'Request failed.';
			updateAssistantMessage(placeholderId, {
				content: messages.find((messageItem) => messageItem.id === placeholderId)?.content || 'Unable to complete the request.'
			});
		} finally {
			currentAssistantId = '';
			isLoading = false;
		}
	}

	function appendAssistantToken(messageId: string, token: string) {
		messages = messages.map((message) =>
			message.id === messageId
				? {
						...message,
						content: message.content + token
					}
				: message
		);
	}

	function applyFinalAssistantResponse(messageId: string, response: ChatResponse) {
		messages = messages.map((message) =>
			message.id === messageId
				? {
						...message,
						content: response.answer,
						sources: response.sources,
						route: response.route,
						cached: response.cached
					}
				: message
		);
	}

	function updateAssistantMessage(messageId: string, patch: Partial<Message>) {
		messages = messages.map((message) =>
			message.id === messageId
				? {
						...message,
						...patch
					}
				: message
		);
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			void sendMessage();
		}
	}
</script>

<svelte:head>
	<title>DocsRAG Chat</title>
	<meta
		name="description"
		content="Streaming documentation chat UI for Claude Code, Cursor, Opencode, Codex, Hermes, and OpenClaw."
	/>
</svelte:head>

<div class="app-shell">
	<div class="chat-panel">
		<header class="header">
			<div>
				<p class="eyebrow">DocsRAG</p>
				<h1>AI tool documentation chat</h1>
			</div>
			<p class="subtitle">Dark theme, streaming answers, and source citations.</p>
		</header>

		<section class="messages" aria-live="polite">
			{#each messages as message (message.id)}
				<article class:assistant={message.role === 'assistant'} class:user={message.role === 'user'}>
					<div class="message-meta">
						<span>{message.role === 'user' ? 'You' : 'Assistant'}</span>
						{#if message.route}
							<span class="pill">{message.route}</span>
						{/if}
						{#if message.cached}
							<span class="pill muted">cached</span>
						{/if}
					</div>
					<div class="bubble {message.role}">
						<pre>{message.content || (message.id === currentAssistantId ? 'Streaming…' : '')}</pre>
					</div>

					{#if message.sources.length > 0}
						<div class="sources">
							<h2>Sources</h2>
							<ul>
								{#each message.sources as source}
									<li>
										<a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
										<div class="source-meta">
											<span>{source.provider}</span>
											{#if source.doc_type}<span>{source.doc_type}</span>{/if}
											{#if source.section}<span>{source.section}</span>{/if}
										</div>
									</li>
								{/each}
							</ul>
						</div>
					{/if}
				</article>
			{/each}

			{#if isLoading}
				<div class="loading-row">
					<span class="spinner" aria-hidden="true"></span>
					<span>Generating answer…</span>
				</div>
			{/if}
		</section>

		{#if errorMessage}
			<div class="error-banner" role="alert">{errorMessage}</div>
		{/if}

		<footer class="composer">
			<label class="sr-only" for="query">Ask a documentation question</label>
			<textarea
				id="query"
				bind:value={query}
				onkeydown={handleKeydown}
				placeholder="Ask about installation, configuration, API usage, pricing, or troubleshooting..."
				disabled={isLoading}
				rows="4"
			/>
			<div class="composer-actions">
				<div class="session-indicator">
					{#if sessionId}
						<span>Session: {sessionId}</span>
					{:else}
						<span>New session</span>
					{/if}
				</div>
				<button type="button" onclick={() => void sendMessage()} disabled={isLoading || !query.trim()}>
					{isLoading ? 'Streaming…' : 'Send'}
				</button>
			</div>
		</footer>
	</div>
</div>

<style>
	:global(html),
	:global(body) {
		margin: 0;
		min-height: 100%;
		background: #0b1020;
		color: #e5ecff;
		font-family:
			Inter,
			system-ui,
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			sans-serif;
	}

	:global(body) {
		background:
			radial-gradient(circle at top, rgba(52, 211, 153, 0.12), transparent 25%),
			linear-gradient(180deg, #0b1020 0%, #11192e 100%);
	}

	.app-shell {
		min-height: 100vh;
		display: flex;
		justify-content: center;
		padding: 2rem;
		box-sizing: border-box;
	}

	.chat-panel {
		width: min(980px, 100%);
		display: grid;
		grid-template-rows: auto 1fr auto auto;
		gap: 1rem;
		background: rgba(10, 15, 29, 0.78);
		backdrop-filter: blur(14px);
		border: 1px solid rgba(148, 163, 184, 0.18);
		border-radius: 24px;
		box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
		padding: 1.25rem;
		min-height: calc(100vh - 4rem);
	}

	.header {
		display: flex;
		justify-content: space-between;
		align-items: end;
		gap: 1rem;
		padding-bottom: 0.5rem;
		border-bottom: 1px solid rgba(148, 163, 184, 0.12);
	}

	.eyebrow {
		margin: 0 0 0.35rem;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		font-size: 0.72rem;
		color: #7dd3fc;
	}

	h1 {
		margin: 0;
		font-size: clamp(1.5rem, 3vw, 2.2rem);
	}

	.subtitle {
		margin: 0;
		color: #94a3b8;
		max-width: 24rem;
		text-align: right;
	}

	.messages {
		overflow: auto;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding-right: 0.35rem;
	}

	article {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
	}

	article.user {
		align-items: flex-end;
	}

	.message-meta {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		font-size: 0.78rem;
		color: #94a3b8;
	}

	.bubble {
		max-width: min(78ch, 100%);
		padding: 0.95rem 1rem;
		border-radius: 18px;
		border: 1px solid rgba(148, 163, 184, 0.12);
	}

	.bubble.user {
		background: linear-gradient(135deg, #2563eb, #1d4ed8);
		color: white;
	}

	.bubble.assistant {
		background: rgba(15, 23, 42, 0.92);
	}

	pre {
		margin: 0;
		white-space: pre-wrap;
		word-break: break-word;
		font: inherit;
		line-height: 1.55;
	}

	.pill {
		padding: 0.18rem 0.5rem;
		border-radius: 999px;
		background: rgba(125, 211, 252, 0.12);
		border: 1px solid rgba(125, 211, 252, 0.2);
		color: #bae6fd;
	}

	.pill.muted {
		background: rgba(148, 163, 184, 0.12);
		border-color: rgba(148, 163, 184, 0.2);
		color: #cbd5e1;
	}

	.sources {
		padding: 0.9rem 1rem;
		background: rgba(15, 23, 42, 0.6);
		border: 1px solid rgba(148, 163, 184, 0.12);
		border-radius: 16px;
	}

	.sources h2 {
		margin: 0 0 0.75rem;
		font-size: 0.95rem;
	}

	.sources ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.75rem;
	}

	.sources li {
		display: grid;
		gap: 0.35rem;
	}

	.sources a {
		color: #93c5fd;
		text-decoration: none;
		font-weight: 600;
	}

	.sources a:hover {
		text-decoration: underline;
	}

	.source-meta {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
		font-size: 0.78rem;
		color: #94a3b8;
	}

	.loading-row {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		color: #cbd5e1;
		font-size: 0.92rem;
	}

	.spinner {
		width: 0.95rem;
		height: 0.95rem;
		border-radius: 50%;
		border: 2px solid rgba(148, 163, 184, 0.25);
		border-top-color: #7dd3fc;
		animation: spin 0.8s linear infinite;
	}

	.error-banner {
		padding: 0.85rem 1rem;
		border-radius: 14px;
		background: rgba(127, 29, 29, 0.35);
		border: 1px solid rgba(248, 113, 113, 0.35);
		color: #fecaca;
	}

	.composer {
		display: grid;
		gap: 0.85rem;
	}

	textarea {
		width: 100%;
		resize: vertical;
		min-height: 6.5rem;
		box-sizing: border-box;
		padding: 1rem;
		border-radius: 16px;
		border: 1px solid rgba(148, 163, 184, 0.18);
		background: rgba(15, 23, 42, 0.9);
		color: #e5ecff;
		font: inherit;
	}

	textarea:focus {
		outline: 2px solid rgba(125, 211, 252, 0.45);
		outline-offset: 2px;
	}

	textarea:disabled {
		opacity: 0.7;
		cursor: not-allowed;
	}

	.composer-actions {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
	}

	.session-indicator {
		font-size: 0.8rem;
		color: #94a3b8;
	}

	button {
		border: 0;
		border-radius: 999px;
		padding: 0.8rem 1.2rem;
		background: linear-gradient(135deg, #38bdf8, #2563eb);
		color: white;
		font: inherit;
		font-weight: 700;
		cursor: pointer;
		transition:
			transform 0.15s ease,
			opacity 0.15s ease;
	}

	button:hover:enabled {
		transform: translateY(-1px);
	}

	button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (max-width: 720px) {
		.app-shell {
			padding: 0;
		}

		.chat-panel {
			min-height: 100vh;
			border-radius: 0;
			padding: 1rem;
		}

		.header,
		.composer-actions {
			flex-direction: column;
			align-items: stretch;
		}

		.subtitle {
			text-align: left;
			max-width: none;
		}
	}
</style>
