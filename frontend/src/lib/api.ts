export interface SourceDocument {
	title: string;
	url: string;
	provider: string;
	tool_name?: string;
	doc_type?: string;
	section?: string;
	score?: number;
	source?: string;
}

export interface QueryProfile {
	query_type: string;
	providers: string[];
	tools: string[];
	all_labels: string[];
	is_multi_provider: boolean;
	is_comparison: boolean;
	is_out_of_scope: boolean;
}

export interface ChatRequest {
	query: string;
	session_id?: string;
}

export interface ChatResponse {
	session_id: string;
	answer: string;
	route: string;
	query: string;
	cached: boolean;
	sources: SourceDocument[];
	query_profile: QueryProfile;
}

export type StreamEvent =
	| { type: 'session'; session_id: string }
	| { type: 'meta'; route: string; sources: SourceDocument[]; cached: boolean; session_id?: string }
	| { type: 'token'; text: string; session_id?: string }
	| { type: 'done'; response: ChatResponse; session_id?: string }
	| { type: 'error'; detail: string; session_id?: string };

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000';

export async function postChat(payload: ChatRequest): Promise<ChatResponse> {
	const response = await fetch(`${API_BASE_URL}/chat`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(payload)
	});

	if (!response.ok) {
		throw new Error(await readErrorMessage(response, 'Chat request failed.'));
	}

	return (await response.json()) as ChatResponse;
}

export async function streamChat(
	payload: ChatRequest,
	handlers: {
		onEvent?: (event: StreamEvent) => void;
		onToken?: (token: string) => void;
		onDone?: (response: ChatResponse) => void;
		onError?: (message: string) => void;
	}
): Promise<void> {
	const response = await fetch(`${API_BASE_URL}/chat/stream`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(payload)
	});

	if (!response.ok) {
		const message = await readErrorMessage(response, 'Streaming request failed.');
		handlers.onError?.(message);
		throw new Error(message);
	}

	if (!response.body) {
		const message = 'Streaming response body is not available.';
		handlers.onError?.(message);
		throw new Error(message);
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';

	while (true) {
		const { done, value } = await reader.read();
		console.log(performance.now().toFixed(0), 'reader.read() returned, done:', done, 'bytes:', value?.length);
		if (done) {
			break;
		}

		buffer += decoder.decode(value, { stream: true });
		const frames = buffer.split('\n\n');
		buffer = frames.pop() ?? '';

		for (const frame of frames) {
			const parsed = parseSseFrame(frame);
			if (!parsed) {
				continue;
			}

			handlers.onEvent?.(parsed);

			if (parsed.type === 'token') {
				handlers.onToken?.(parsed.text);
			} else if (parsed.type === 'done') {
				handlers.onDone?.(parsed.response);
			} else if (parsed.type === 'error') {
				handlers.onError?.(parsed.detail);
			}
		}
	}
}

function parseSseFrame(frame: string): StreamEvent | null {
	const dataLines = frame
		.split('\n')
		.map((line) => line.trim())
		.filter((line) => line.startsWith('data:'))
		.map((line) => line.slice(5).trim());

	if (dataLines.length === 0) {
		return null;
	}

	return JSON.parse(dataLines.join('\n')) as StreamEvent;
}

async function readErrorMessage(response: Response, fallbackMessage: string): Promise<string> {
	try {
		const payload = (await response.json()) as { detail?: string };
		return payload.detail ?? fallbackMessage;
	} catch {
		return fallbackMessage;
	}
}
