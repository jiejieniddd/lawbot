import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  message,
} from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import {
  CUSTOM_MODEL_VALUE,
  LOCAL_LLM_CATALOG,
  findProviderEntry,
  getModelsForProvider,
  presetModelIds,
  type LlmCatalog,
} from '../constants/llmCatalog'

type Provider = {
  id: string
  name: string
  provider: string
  base_url: string | null
  default_model: string
  priority: number
  enabled: boolean
  api_key_masked: string
  created_at?: string | null
  updated_at?: string | null
}

type ProviderForm = {
  name: string
  provider: string
  base_url?: string
  api_key?: string
  default_model: string
  priority: number
  enabled: boolean
}

export default function ProvidersPage() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Provider | null>(null)
  const [modelPreset, setModelPreset] = useState<string>('')
  const [form] = Form.useForm<ProviderForm>()
  const qc = useQueryClient()
  const watchedProvider = Form.useWatch('provider', form)

  const { data: catalog = LOCAL_LLM_CATALOG } = useQuery({
    queryKey: ['llm-catalog'],
    queryFn: async (): Promise<LlmCatalog> => {
      try {
        const res = await api.get<LlmCatalog>('/api/admin/llm-providers/catalog')
        if (res.data?.providers?.length) return res.data
      } catch {
        /* fall through */
      }
      return LOCAL_LLM_CATALOG
    },
    staleTime: 60_000,
  })

  const providerOptions = useMemo(
    () => catalog.providers.map((p) => ({ value: p.value, label: p.label })),
    [catalog],
  )

  const modelOptions = useMemo(
    () => getModelsForProvider(catalog, watchedProvider || 'openai_compatible'),
    [catalog, watchedProvider],
  )

  const showCustomModel = modelPreset === CUSTOM_MODEL_VALUE

  const { data, isLoading } = useQuery({
    queryKey: ['llm-providers'],
    queryFn: async () => (await api.get<Provider[]>('/api/admin/llm-providers')).data,
  })

  const create = useMutation({
    mutationFn: async (values: ProviderForm) =>
      api.post('/api/admin/llm-providers', {
        name: values.name,
        provider: values.provider,
        base_url: values.base_url || null,
        api_key: values.api_key,
        default_model: values.default_model,
        priority: values.priority,
        enabled: values.enabled,
      }),
    onSuccess: () => {
      message.success('已创建供应商')
      closeModal()
      qc.invalidateQueries({ queryKey: ['llm-providers'] })
    },
    onError: () => message.error('创建失败'),
  })

  const update = useMutation({
    mutationFn: async ({ id, values }: { id: string; values: ProviderForm }) => {
      const body: Record<string, unknown> = {
        name: values.name,
        provider: values.provider,
        base_url: values.base_url || null,
        default_model: values.default_model,
        priority: values.priority,
        enabled: values.enabled,
      }
      if (values.api_key?.trim()) body.api_key = values.api_key.trim()
      return api.patch(`/api/admin/llm-providers/${id}`, body)
    },
    onSuccess: () => {
      message.success('已更新')
      closeModal()
      qc.invalidateQueries({ queryKey: ['llm-providers'] })
    },
    onError: () => message.error('更新失败'),
  })

  const toggle = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patch(`/api/admin/llm-providers/${id}`, { enabled }),
    onSuccess: () => {
      message.success('已更新启用状态')
      qc.invalidateQueries({ queryKey: ['llm-providers'] })
    },
    onError: () => message.error('更新失败'),
  })

  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/api/admin/llm-providers/${id}`),
    onSuccess: () => {
      message.success('已删除')
      qc.invalidateQueries({ queryKey: ['llm-providers'] })
    },
    onError: () => message.error('删除失败'),
  })

  const testConn = useMutation({
    mutationFn: async (id: string) =>
      (await api.post<{ ok: boolean; message: string }>(`/api/admin/llm-providers/${id}/test`))
        .data,
    onSuccess: (res) => {
      if (res.ok) message.success(res.message || '连通正常')
      else message.error(res.message || '连通失败')
    },
    onError: () => message.error('测试请求失败'),
  })

  function closeModal() {
    setOpen(false)
    setEditing(null)
    setModelPreset('')
    form.resetFields()
  }

  function onProviderChange(provider: string) {
    setModelPreset('')
    const entry = findProviderEntry(catalog, provider)
    form.setFieldsValue({
      provider,
      default_model: '',
      // Always follow the selected vendor; clear when catalog has no recommendation
      base_url: entry?.recommended_base_url || '',
    })
  }

  function onModelPresetChange(value: string) {
    setModelPreset(value)
    if (value === CUSTOM_MODEL_VALUE) {
      form.setFieldsValue({ default_model: '' })
    } else {
      form.setFieldsValue({ default_model: value })
    }
  }

  function openCreate() {
    setEditing(null)
    const defaultProvider = 'deepseek'
    const entry = findProviderEntry(catalog, defaultProvider)
    setModelPreset('')
    form.setFieldsValue({
      name: '',
      provider: defaultProvider,
      base_url: entry?.recommended_base_url || '',
      api_key: '',
      default_model: '',
      priority: 100,
      enabled: true,
    })
    setOpen(true)
  }

  function openEdit(row: Provider) {
    setEditing(row)
    const presets = presetModelIds(catalog, row.provider)
    const preset = presets.has(row.default_model) ? row.default_model : CUSTOM_MODEL_VALUE
    setModelPreset(preset)
    form.setFieldsValue({
      name: row.name,
      provider: row.provider,
      base_url: row.base_url || '',
      api_key: '',
      default_model: row.default_model,
      priority: row.priority,
      enabled: row.enabled,
    })
    setOpen(true)
  }

  function onFinish(values: ProviderForm) {
    if (!values.default_model?.trim()) {
      message.error('请选择或填写 Default Model')
      return
    }
    if (editing) update.mutate({ id: editing.id, values })
    else create.mutate(values)
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>模型供应商</h2>
        <Button type="primary" onClick={openCreate}>
          新建供应商
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={isLoading}
        dataSource={data}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: 'Provider', dataIndex: 'provider' },
          { title: 'Model', dataIndex: 'default_model' },
          { title: '优先级', dataIndex: 'priority', width: 90 },
          {
            title: '启用',
            dataIndex: 'enabled',
            width: 90,
            render: (enabled: boolean, row) => (
              <Switch
                checked={enabled}
                loading={toggle.isPending}
                onChange={(v) => toggle.mutate({ id: row.id, enabled: v })}
              />
            ),
          },
          {
            title: 'Key（脱敏）',
            dataIndex: 'api_key_masked',
            render: (v: string) => <code style={{ fontSize: 12 }}>{v}</code>,
          },
          {
            title: '操作',
            width: 220,
            render: (_, row) => (
              <Space wrap>
                <Button size="small" onClick={() => openEdit(row)}>
                  编辑
                </Button>
                <Button
                  size="small"
                  loading={testConn.isPending}
                  onClick={() => testConn.mutate(row.id)}
                >
                  测试连通
                </Button>
                <Popconfirm title="确认删除该供应商？" onConfirm={() => remove.mutate(row.id)}>
                  <Button danger size="small">
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? '编辑模型供应商' : '新建模型供应商'}
        open={open}
        onCancel={closeModal}
        onOk={() => form.submit()}
        confirmLoading={create.isPending || update.isPending}
        destroyOnHidden
        width={560}
      >
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="例如 DeepSeek 主线路" />
          </Form.Item>
          <Form.Item name="provider" label="Provider" rules={[{ required: true }]}>
            <Select options={providerOptions} onChange={onProviderChange} />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL">
            <Input placeholder="随 Provider 自动填充推荐地址，可手动改" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={editing ? 'API Key（留空则不修改）' : 'API Key'}
            rules={editing ? [] : [{ required: true, message: '请输入供应商 API Key' }]}
          >
            <Input.Password placeholder={editing ? '留空保持原密钥' : '供应商密钥，仅写入时明文'} />
          </Form.Item>
          <Form.Item label="Default Model" required>
            <Select
              value={modelPreset || undefined}
              placeholder="选择预设模型或自定义"
              options={modelOptions}
              onChange={onModelPresetChange}
              style={{ width: '100%' }}
            />
          </Form.Item>
          {showCustomModel ? (
            <Form.Item
              name="default_model"
              label="自定义 Model ID"
              rules={[{ required: true, message: '请填写自定义 model id' }]}
            >
              <Input placeholder="真实 model id，例如 my-deployed-model" />
            </Form.Item>
          ) : (
            <Form.Item
              name="default_model"
              hidden
              rules={[{ required: true, message: '请选择模型' }]}
            >
              <Input />
            </Form.Item>
          )}
          <Form.Item name="priority" label="优先级（越小越优先）" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
