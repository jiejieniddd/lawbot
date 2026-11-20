import { Button, Card, Descriptions, Form, Input, InputNumber, Select, Space, Switch, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
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

function errorDetail(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

export default function SettingsPage() {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission('settings:write')
  const queryClient = useQueryClient()
  const [form] = Form.useForm<MailForm>()

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => (await api.get<Record<string, unknown>>('/api/admin/settings')).data,
  })

  const mail = useQuery({
    queryKey: ['settings-mail'],
    queryFn: async () => (await api.get<MailSettings>('/api/admin/settings/mail')).data,
  })

  useEffect(() => {
    if (!mail.data) return
    form.setFieldsValue({ ...mail.data, smtp_password: '' })
  }, [form, mail.data])

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
        from_name: values.from_name ?? 'LawBot',
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

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="系统设置（脱敏）" loading={isLoading}>
        <Descriptions column={1} bordered size="small">
          {data &&
            Object.entries(data).map(([k, v]) => (
              <Descriptions.Item key={k} label={k}>
                {Array.isArray(v) ? v.join(', ') : String(v)}
              </Descriptions.Item>
            ))}
        </Descriptions>
      </Card>

      <Card title="邮件 / 找回密码" loading={mail.isLoading}>
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => save.mutate(values)}
          initialValues={{
            enabled: false,
            smtp_port: 587,
            smtp_security: 'starttls',
            from_name: 'LawBot',
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
          <Form.Item name="smtp_port" label="SMTP port" rules={[{ required: true, message: '请输入端口' }]}>
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
              placeholder={mail.data?.password_configured ? '已设置，留空则不修改' : '请输入 SMTP 密码'}
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
      </Card>
    </Space>
  )
}
