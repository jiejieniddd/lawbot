import type { ReactNode } from 'react'
import {
  ApiOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'

export type NavItem = {
  key: string
  label: string
  icon: ReactNode
  permission?: string
}

export const NAV_ITEMS: NavItem[] = [
  { key: '/', icon: <DashboardOutlined />, label: '仪表盘', permission: 'stats:read' },
  { key: '/users/clients', icon: <UserOutlined />, label: 'C端用户', permission: 'user:list' },
  { key: '/users/admins', icon: <TeamOutlined />, label: '管理员', permission: 'admin:manage' },
  { key: '/roles', icon: <SafetyCertificateOutlined />, label: '角色管理', permission: 'role:manage' },
  { key: '/audit', icon: <FileSearchOutlined />, label: '会话审计', permission: 'audit:read' },
  { key: '/providers', icon: <ApiOutlined />, label: '模型供应商', permission: 'provider:manage' },
  { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库', permission: 'knowledge:read' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置', permission: 'settings:read' },
]
