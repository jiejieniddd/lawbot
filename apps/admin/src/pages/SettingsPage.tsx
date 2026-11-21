import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  message,
} from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

type MailSettings = {
  enabled: boolean
  smtp_host: string
  smtp_port: number
  smtp_security: 'none' | 'starttls' | 'ssl'
  smtp_username: string
  password_configured: boolean
  from_address: string
  from_name: string
  code_ttl_minutes: number
  resend_interval_seconds: number
}

type MailForm = MailSettings & { smtp_password?: string }

type EmbeddingSettings = {
  mode: 'fake' | 'litellm' | 'auto'
  embedding_model: string
  api_base: string
  embedding_dim: number
  reuse_llm_provider: boolean
  api_key_configured: boolean
  effective_mode: 'fake' | 'litellm' | 'auto'
  source: string
  reindex_required_hint: string
  detail?: string
}

type EmbeddingForm = EmbeddingSettings & { api_key?: string }

type SettingsSection = 'overview' | 'embedding' | 'mail'

function errorDetail(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

const NAV: { id: SettingsSection; label: string; icon: string }[] = [
  { id: 'overview', label: '运行概览', icon: '◇' },
  { id: 'embedding', label: '向量检索', icon: '▣' },
  { id: 'mail', label: '邮件通知', icon: '✉' },
]

export default function SettingsPage() {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission('settings:write')
  const queryClient = useQueryClient()
  const [form] = Form.useForm<MailForm>()
  const [embForm] = Form.useForm<EmbeddingForm>()
  const [activeSection, setActiveSection] = useState<SettingsSection>('overview')

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => (await api.get<Record<string, unknown>>('/api/admin/settings')).data,
  })

  const mail = useQuery({
    queryKey: ['settings-mail'],
    queryFn: async () => (await api.get<MailSettings>('/api/admin/settings/mail')).data,
  })

  const embedding = useQuery({
    queryKey: ['settings-embedding'],
    queryFn: async () => (await api.get<EmbeddingSettings>('/api/admin/settings/embedding')).data,
  })

  useEffect(() => {
    if (!mail.data) return
    form.setFieldsValue({ ...mail.data, smtp_password: '' })
  }, [form, mail.data])

  useEffect(() => {
    if (!embedding.data) return
    embForm.setFieldsValue({ ...embedding.data, api_key: '' })
  }, [embForm, embedding.data])

  const save = useMutation({
    mutationFn: async (values: MailForm) => {
      const body = {
        enabled: values.enabled,
        smtp_host: values.smtp_host ?? '',
        smtp_port: values.smtp_port,
        smtp_security: values.smtp_security,
        smtp_username: values.smtp_username ?? '',
        smtp_password: values.smtp_password?.trim() || '',
        from_address: values.from_address ?? '',
        from_name: values.from_name ?? 'CareerBot',
        code_ttl_minutes: values.code_ttl_minutes,
        resend_interval_seconds: values.resend_interval_seconds,
      }
      return (await api.put<MailSettings>('/api/admin/settings/mail', body)).data
    },
    onSuccess: (saved) => {
      message.success('已保存')
      form.setFieldsValue({ ...saved, smtp_password: '' })
      queryClient.setQueryData(['settings-mail'], saved)
    },
    onError: (error) => message.error(errorDetail(error, '保存失败')),
  })

  const sendTest = useMutation({
    mutationFn: async (to: string) =>
      (await api.post<{ detail: string }>('/api/admin/settings/mail/test', { to })).data,
    onSuccess: (res) => message.success(res.detail || '测试邮件已发送'),
    onError: (error) => message.error(errorDetail(error, '发送失败')),
  })

  const saveEmb = useMutation({
    mutationFn: async (values: EmbeddingForm) => {
      const body = {
        mode: values.mode,
        embedding_model: values.embedding_model ?? '',
        api_key: values.api_key?.trim() || '',
        api_base: values.api_base ?? '',
        embedding_dim: values.embedding_dim,
        reuse_llm_provider: !!values.reuse_llm_provider,
      }
      return (await api.put<EmbeddingSettings>('/api/admin/settings/embedding', body)).data
    },
    onSuccess: (saved) => {
      message.success(saved.detail || 'Embedding 已保存。修改 mode / model / dim 后必须重新导入知识库。')
      embForm.setFieldsValue({ ...saved, api_key: '' })
      queryClient.setQueryData(['settings-embedding'], saved)
    },
    onError: (error) => message.error(errorDetail(error, '保存失败')),
  })

  const testEmb = useMutation({
    mutationFn: async () => {
      const values = embForm.getFieldsValue()
      const body = {
        mode: values.mode,
        embedding_model: values.embedding_model ?? '',
        api_key: values.api_key?.trim() || '',
        api_base: values.api_base ?? '',
        embedding_dim: values.embedding_dim,
        reuse_llm_provider: !!values.reuse_llm_provider,
      }
      return (
        await api.post<{ ok: boolean; dim?: number; detail: string }>(
          '/api/admin/settings/embedding/test',
          body,
        )
      ).data
    },
    onSuccess: (res) => {
      if (res.ok) message.success(res.detail || `连通成功 dim=${res.dim}`)
      else message.error(res.detail || '测试失败')
    },
    onError: (error) => message.error(errorDetail(error, 'Embedding 测试失败')),
  })

  const effective = embedding.data?.effective_mode
  const usingFake = effective === 'fake'

  return (
    <div className="admin-settings-shell">
      <header className="admin-settings-head">
        <h1>系统设置</h1>
      </header>
      <div className="admin-settings-body">
        <nav className="admin-settings-nav" aria-label="设置分类">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`admin-settings-nav-item${activeSection === item.id ? ' active' : ''}`}
              onClick={() => setActiveSection(item.id)}
            >
              <span className="admin-settings-nav-icon" aria-hidden>
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="admin-settings-pane">
          {activeSection === 'overview' ? (
            <div className="admin-settings-block" style={{ opacity: isLoading ? 0.6 : 1 }}>
              <Descriptions column={1} bordered size="small">
                {data &&
                  Object.entries(data).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>
                      {Array.isArray(v) ? v.join(', ') : String(v)}
                    </Descriptions.Item>
                  ))}
              </Descriptions>
            </div>
          ) : null}

          {activeSection === 'embedding' ? (
            <div className="admin-settings-block" style={{ opacity: embedding.isLoading ? 0.6 : 1 }}>
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message="向量嵌入配置（不是分词、也不是聊天模型）"
                description={
                  embedding.data?.reindex_required_hint ||
                  '修改 mode / model / dim 后必须重新导入知识库，勿与旧索引混用。'
                }
              />
              <Space style={{ marginBottom: 12 }}>
                <span>当前生效：</span>
                {usingFake ? (
                  <Tag color="orange">假向量 fake</Tag>
                ) : (
                  <Tag color="green">真向量 litellm</Tag>
                )}
                {embedding.data?.source ? <Tag>凭证来源 {embedding.data.source}</Tag> : null}
              </Space>
              <Form
                form={embForm}
                layout="vertical"
                onFinish={(values) => saveEmb.mutate(values)}
                initialValues={{
                  mode: 'auto',
                  embedding_dim: 384,
                  reuse_llm_provider: false,
                  embedding_model: '',
                  api_base: '',
                }}
              >
                <Form.Item
                  name="mode"
                  label="Mode"
                  rules={[{ required: true, message: '请选择 mode' }]}
                  extra="fake=本地哈希向量；litellm=调用嵌入 API；auto=有模型+Key 则 litellm 否则 fake"
                >
                  <Select
                    options={[
                      { value: 'auto', label: 'auto' },
                      { value: 'litellm', label: 'litellm（真向量）' },
                      { value: 'fake', label: 'fake（本地假向量）' },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="embedding_model"
                  label="Embedding 模型名"
                  extra="填向量模型（如 qwen3.7-text-embedding-flash / text-embedding-v3），不要填聊天模型；有 API Base 时也可写 openai/模型名"
                >
                  <Input placeholder="qwen3.7-text-embedding-flash" autoComplete="off" />
                </Form.Item>
                <Form.Item
                  name="api_key"
                  label="API Key"
                  extra={
                    embedding.data?.api_key_configured
                      ? '已设置。留空表示不修改。'
                      : '尚未设置（可勾选复用聊天供应商密钥）'
                  }
                >
                  <Input.Password
                    autoComplete="new-password"
                    placeholder={
                      embedding.data?.api_key_configured
                        ? '已设置，留空则不修改'
                        : 'Embedding API Key'
                    }
                  />
                </Form.Item>
                <Form.Item name="api_base" label="API Base（可选）">
                  <Input
                    placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                    autoComplete="off"
                  />
                </Form.Item>
                <Form.Item
                  name="embedding_dim"
                  label="向量维度"
                  rules={[{ required: true, message: '请输入维度' }]}
                  extra="改维度后必须全量重灌索引"
                >
                  <InputNumber min={8} max={8192} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item
                  name="reuse_llm_provider"
                  label="复用聊天供应商 Key/Base"
                  valuePropName="checked"
                  extra="仍使用上方 embedding_model；不会把聊天模型名当成嵌入模型"
                >
                  <Switch />
                </Form.Item>
                <Space>
                  <Button
                    type="primary"
                    htmlType="submit"
                    disabled={!canWrite}
                    loading={saveEmb.isPending}
                  >
                    保存
                  </Button>
                  <Button
                    disabled={!canWrite}
                    loading={testEmb.isPending}
                    onClick={() => testEmb.mutate()}
                  >
                    测试连通
                  </Button>
                </Space>
              </Form>
            </div>
          ) : null}

          {activeSection === 'mail' ? (
            <div className="admin-settings-block" style={{ opacity: mail.isLoading ? 0.6 : 1 }}>
              <Form
                form={form}
                layout="vertical"
                onFinish={(values) => save.mutate(values)}
                initialValues={{
                  enabled: false,
                  smtp_port: 587,
                  smtp_security: 'starttls',
                  from_name: 'CareerBot',
                  code_ttl_minutes: 10,
                  resend_interval_seconds: 60,
                }}
              >
                <Form.Item name="enabled" label="启用" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item name="smtp_host" label="SMTP host">
                  <Input autoComplete="off" />
                </Form.Item>
                <Form.Item
                  name="smtp_port"
                  label="SMTP port"
                  rules={[{ required: true, message: '请输入端口' }]}
                >
                  <InputNumber min={1} max={65535} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="smtp_security" label="TLS / SSL" rules={[{ required: true }]}>
                  <Select
                    options={[
                      { value: 'none', label: '无' },
                      { value: 'starttls', label: 'STARTTLS' },
                      { value: 'ssl', label: 'SSL' },
                    ]}
                  />
                </Form.Item>
                <Form.Item name="smtp_username" label="SMTP 用户名">
                  <Input autoComplete="off" />
                </Form.Item>
                <Form.Item
                  name="smtp_password"
                  label="SMTP 密码"
                  extra={mail.data?.password_configured ? '已设置。留空表示不修改。' : '尚未设置'}
                >
                  <Input.Password
                    autoComplete="new-password"
                    placeholder={
                      mail.data?.password_configured ? '已设置，留空则不修改' : '请输入 SMTP 密码'
                    }
                  />
                </Form.Item>
                <Form.Item name="from_address" label="发件人地址">
                  <Input autoComplete="off" />
                </Form.Item>
                <Form.Item name="from_name" label="发件人名称">
                  <Input />
                </Form.Item>
                <Form.Item
                  name="code_ttl_minutes"
                  label="验证码有效分钟数"
                  rules={[{ required: true, message: '请输入有效分钟数' }]}
                >
                  <InputNumber min={1} max={60} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item
                  name="resend_interval_seconds"
                  label="重发间隔秒数"
                  rules={[{ required: true, message: '请输入重发间隔' }]}
                >
                  <InputNumber min={30} max={3600} style={{ width: '100%' }} />
                </Form.Item>
                <Button type="primary" htmlType="submit" disabled={!canWrite} loading={save.isPending}>
                  保存
                </Button>
              </Form>

              <Form
                layout="inline"
                style={{ marginTop: 24 }}
                onFinish={(values: { to: string }) => sendTest.mutate(values.to.trim())}
              >
                <Form.Item
                  name="to"
                  label="测试收件人"
                  rules={[
                    { required: true, message: '请输入邮箱' },
                    { type: 'email', message: '请输入有效邮箱' },
                  ]}
                >
                  <Input placeholder="name@example.com" style={{ width: 260 }} />
                </Form.Item>
                <Form.Item>
                  <Button htmlType="submit" disabled={!canWrite} loading={sendTest.isPending}>
                    发送测试邮件
                  </Button>
                </Form.Item>
              </Form>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
