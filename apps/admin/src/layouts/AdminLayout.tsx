import { Layout, Menu, Spin } from 'antd'
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
      <div className="admin-loading">
        <Spin size="large" tip="加载账号权限…" />
      </div>
    )
  }

  return (
    <Layout className="admin-shell">
      <Sider width={232} theme="light" className="admin-sider" breakpoint="lg" collapsedWidth={0}>
        <div className="admin-brand">
          CareerBot
          <span className="admin-brand-sub">Admin</span>
        </div>
        <Menu
          className="admin-menu"
          theme="light"
          mode="inline"
          selectedKeys={[selected]}
          onClick={({ key }) => nav(key)}
          items={items}
        />
      </Sider>
      <Layout className="admin-main">
        <Header className="admin-header">
          <span className="admin-header-meta">
            管理控制台
            {me?.display_name || me?.email ? ` · ${me.display_name || me.email}` : ''}
          </span>
          <button
            type="button"
            className="admin-logout"
            onClick={() => {
              void adminLogout().finally(() => nav('/login'))
            }}
          >
            退出
          </button>
        </Header>
        <Content className="admin-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
