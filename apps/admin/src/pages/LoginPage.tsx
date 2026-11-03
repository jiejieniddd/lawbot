import { Alert, Button, Card, Form, Input, Typography } from 'antd'
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
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: 'linear-gradient(160deg,#d9e2ec,#f7f4ef)',
      }}
    >
      <Card style={{ width: 400 }}>
        <Typography.Title level={3} style={{ fontFamily: 'Georgia, serif' }}>
          律问后台
        </Typography.Title>
        {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item name="email" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input placeholder="请输入账号" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
