import { Layout, Menu, Typography } from 'antd'
import {
  ApiOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { adminLogout } from '../api/client'

const { Header, Sider, Content } = Layout

export default function AdminLayout() {
  const nav = useNavigate()
  const loc = useLocation()
  const selected =
    loc.pathname === '/'
      ? '/'
      : loc.pathname.startsWith('/users/')
        ? loc.pathname
        : `/${loc.pathname.split('/')[1]}`

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="dark" width={220}>
        <div style={{ color: '#fff', padding: 16, fontFamily: 'Georgia, serif', fontSize: 20 }}>
          LawBot Admin
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          onClick={({ key }) => nav(key)}
          items={[
            { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
            { key: '/users/clients', icon: <UserOutlined />, label: 'C端用户' },
            { key: '/users/admins', icon: <TeamOutlined />, label: '管理员' },
            { key: '/audit', icon: <FileSearchOutlined />, label: 'Audit' },
            { key: '/providers', icon: <ApiOutlined />, label: '模型供应商' },
            { key: '/knowledge', icon: <DatabaseOutlined />, label: 'Knowledge' },
            { key: '/settings', icon: <SettingOutlined />, label: 'Settings' },
          ]}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            paddingInline: 24,
          }}
        >
          <Typography.Text type="secondary">法律咨询后台</Typography.Text>
          <a
            onClick={() => {
              void adminLogout().finally(() => nav('/login'))
            }}
          >
            退出
          </a>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
