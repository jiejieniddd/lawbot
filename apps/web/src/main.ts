import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import router from './router'
import './style.css'
import './styles/theme.css'
import { applyThemeToDom, resolveInitialTheme, useThemeStore } from './stores/theme'

/* Apply before mount to avoid flash */
applyThemeToDom(resolveInitialTheme())

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
useThemeStore(pinia).initTheme()
app.use(router).use(ElementPlus).mount('#app')
