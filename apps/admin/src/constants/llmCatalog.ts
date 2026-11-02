export const CUSTOM_MODEL_VALUE = '__custom__'

export type CatalogModel = { value: string; label: string }

export type CatalogProvider = {
  value: string
  label: string
  recommended_base_url?: string | null
  models: CatalogModel[]
}

export type LlmCatalog = { providers: CatalogProvider[] }

function models(...pairs: [string, string][]): CatalogModel[] {
  return [
    ...pairs.map(([value, label]) => ({ value, label })),
    { value: CUSTOM_MODEL_VALUE, label: '自定义' },
  ]
}

/** Local fallback when GET /api/admin/llm-providers/catalog fails. */
export const LOCAL_LLM_CATALOG: LlmCatalog = {
  providers: [
    {
      value: 'deepseek',
      label: 'DeepSeek',
      recommended_base_url: 'https://api.deepseek.com',
      models: models(['deepseek-chat', 'deepseek-chat'], ['deepseek-reasoner', 'deepseek-reasoner']),
    },
    {
      value: 'openai',
      label: 'OpenAI',
      recommended_base_url: 'https://api.openai.com/v1',
      models: models(['gpt-4o', 'gpt-4o'], ['gpt-4o-mini', 'gpt-4o-mini'], ['gpt-4.1', 'gpt-4.1']),
    },
    {
      value: 'dashscope',
      label: '通义千问 (DashScope)',
      recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      models: models(['qwen-plus', 'qwen-plus'], ['qwen-turbo', 'qwen-turbo'], ['qwen-max', 'qwen-max']),
    },
    {
      value: 'zhipu',
      label: '智谱 (Zhipu)',
      recommended_base_url: 'https://open.bigmodel.cn/api/paas/v4',
      models: models(['glm-4', 'glm-4'], ['glm-4-flash', 'glm-4-flash']),
    },
    {
      value: 'moonshot',
      label: 'Moonshot (Kimi)',
      recommended_base_url: 'https://api.moonshot.cn/v1',
      models: models(
        ['moonshot-v1-8k', 'moonshot-v1-8k'],
        ['moonshot-v1-32k', 'moonshot-v1-32k'],
      ),
    },
    {
      value: 'openai_compatible',
      label: 'OpenAI Compatible',
      recommended_base_url: null,
      models: models(['gpt-4o-mini', 'gpt-4o-mini'], ['deepseek-chat', 'deepseek-chat']),
    },
    {
      value: 'ollama',
      label: 'Ollama',
      recommended_base_url: 'http://127.0.0.1:11434',
      models: models(['llama3.2', 'llama3.2'], ['qwen2.5', 'qwen2.5']),
    },
  ],
}

export const PROVIDER_OPTIONS = LOCAL_LLM_CATALOG.providers.map((p) => ({
  value: p.value,
  label: p.label,
}))

export function findProviderEntry(
  catalog: LlmCatalog,
  provider: string,
): CatalogProvider | undefined {
  return catalog.providers.find((p) => p.value === provider)
}

export function getModelsForProvider(catalog: LlmCatalog, provider: string): CatalogModel[] {
  return findProviderEntry(catalog, provider)?.models ?? [
    { value: CUSTOM_MODEL_VALUE, label: '自定义' },
  ]
}

export function presetModelIds(catalog: LlmCatalog, provider: string): Set<string> {
  return new Set(
    getModelsForProvider(catalog, provider)
      .map((m) => m.value)
      .filter((v) => v !== CUSTOM_MODEL_VALUE),
  )
}
