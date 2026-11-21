import { Layout, Menu, Spin, Typography } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { adminLogout } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { NAV_ITEMS } from '../config/nav'

const { Header, Sider, Content } = Layout

export default function AdminLayout() {
  const nav = useNavigate()
  const loc = useLocation()
  const { hasPermission, me, loading } = useAuth()
  const selected =
    loc.pathname === '/'
      ? '/'
      : loc.pathname.startsWith('/users/')
        ? loc.pathname
        : `/${loc.pathname.split('/')[1]}`

  const items = NAV_ITEMS.filter((item) => !item.permission || hasPermission(item.permission)).map(
    (item) => ({
      key: item.key,
      icon: item.icon,
      label: item.label,
    }),
  )

  if (loading) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
        <Spin size="large" tip="加载账号权限…" />
      </div>
    )
  }

  return (
    <Layout className="admin-shell">
      <Sider theme="dark" width={220} className="admin-sider">
        <div style={{ color: '#fff', padding: 16, fontFamily: 'Georgia, serif', fontSize: 20 }}>
          律问后台
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          onClick={({ key }) => nav(key)}
          items={items}
        />
      </Sider>
      <Layout className="admin-main">
        <Header
          style={{
            background: '#fff',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            paddingInline: 24,
            flexShrink: 0,
          }}
        >
          <Typography.Text type="secondary">
            CareerBot 后台
            {me?.display_name || me?.email ? ` · ${me.display_name || me.email}` : ''}
          </Typography.Text>
          <a
            onClick={() => {
              void adminLogout().finally(() => nav('/login'))
            }}
          >
            退出
          </a>
        </Header>
        <Content className="admin-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
