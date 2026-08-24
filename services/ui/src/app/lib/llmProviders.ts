// Shared LLM provider/model catalog for anywhere a user picks a provider and
// model in the UI (AppShell's default-preference settings, the Agent
// Workbench's Definition/Execution model override). Kept in one place so the
// list stays in sync with what the backend's `resolve_provider()`
// (libs/core/llm_provider.py) actually supports.
//
// `openai_compatible` is intentionally not listed here: it requires a custom
// base_url the UI doesn't currently collect anywhere, so it isn't a good fit
// for a fixed provider dropdown. It's still usable directly via the API.
export type LlmProviderOption = {
  value: string;
  label: string;
  models: string[];
};

export const LLM_PROVIDERS: LlmProviderOption[] = [
  { value: "", label: "Platform default", models: [] },
  { value: "mock", label: "Mock (no API calls)", models: [] },
  { value: "openai", label: "OpenAI", models: ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"] },
  {
    value: "anthropic",
    label: "Anthropic",
    models: ["claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
  },
  { value: "gemini", label: "Google Gemini", models: ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-2.5-pro"] },
  {
    value: "bedrock-anthropic",
    label: "Bedrock (Anthropic)",
    models: ["claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
  },
];

export function modelsForProvider(providerValue: string): string[] {
  return LLM_PROVIDERS.find((p) => p.value === providerValue)?.models ?? [];
}
