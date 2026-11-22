import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          token: {
            colorPrimary: '#8b9d77',
            colorError: '#d4a373',
            colorSuccess: '#8b9d77',
            colorInfo: '#75a191',
            colorWarning: '#d4a373',
            colorText: '#5c4033',
            colorTextSecondary: 'rgba(92, 64, 51, 0.7)',
            colorBgBase: '#faf6f1',
            colorBgContainer: '#e9e0d4',
            colorBgLayout: '#faf6f1',
            colorBorder: 'rgba(92, 64, 51, 0.2)',
            colorBorderSecondary: 'rgba(92, 64, 51, 0.12)',
            borderRadius: 20,
            borderRadiusLG: 32,
            fontFamily:
              "'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif",
            fontSize: 15,
            fontWeightStrong: 500,
            controlHeight: 44,
            boxShadow: '0 8px 24px rgba(92, 64, 51, 0.08)',
            boxShadowSecondary: 'none',
          },
          components: {
            Layout: {
              bodyBg: '#faf6f1',
              headerBg: 'transparent',
              siderBg: '#faf6f1',
              triggerBg: '#e9e0d4',
            },
            Menu: {
              itemBg: 'transparent',
              subMenuItemBg: 'transparent',
              itemSelectedBg: 'rgba(139, 157, 119, 0.15)',
              itemHoverBg: 'rgba(139, 157, 119, 0.12)',
              itemColor: '#5c4033',
              itemSelectedColor: '#5c4033',
              activeBarBorderWidth: 0,
            },
            Card: {
              colorBgContainer: '#e9e0d4',
              paddingLG: 32,
            },
            Button: {
              primaryShadow: 'none',
              defaultShadow: 'none',
              defaultBorderColor: 'transparent',
              borderColorDisabled: 'transparent',
              borderRadius: 999,
            },
            Input: {
              activeBorderColor: '#8b9d77',
              hoverBorderColor: 'rgba(92, 64, 51, 0.3)',
              activeShadow: '0 0 0 3px rgba(139, 157, 119, 0.2)',
              colorBgContainer: '#faf6f1',
            },
            Table: {
              headerBg: 'transparent',
              rowHoverBg: 'rgba(139, 157, 119, 0.12)',
              borderColor: 'rgba(92, 64, 51, 0.12)',
            },
            Tag: {
              defaultBg: 'rgba(139, 157, 119, 0.15)',
              defaultColor: '#5c4033',
            },
          },
        }}
      >
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  </StrictMode>,
)
