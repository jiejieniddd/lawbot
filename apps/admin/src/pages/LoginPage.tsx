import { Alert, Button, Form, Input } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setAdminTokens } from '../api/client'

export default function LoginPage() {
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()

  async function onFinish(values: { email: string; password: string }) {
    setLoading(true)
    setError('')
    try {
      const { data } = await api.post('/api/admin/auth/login', values)
      setAdminTokens(data.access_token, data.refresh_token)
      nav('/')
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '登录失败'
      setError(String(msg))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <span className="blob-badge">Admin</span>
        <h1>CareerBot</h1>
        <p className="login-lead">使用管理员账号登录控制台</p>
        {error ? <Alert type="error" message={error} style={{ marginBottom: 16 }} showIcon /> : null}
        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item name="email" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input placeholder="请输入账号" autoComplete="username" size="large" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="密码" autoComplete="current-password" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading} size="large">
            登录
          </Button>
        </Form>
      </div>
    </div>
  )
}
