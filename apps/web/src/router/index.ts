import { createRouter, createWebHistory } from 'vue-router'
import { hasSession } from '../api/client'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import ForgotPasswordView from '../views/ForgotPasswordView.vue'
import ChatView from '../views/ChatView.vue'
import InterviewView from '../views/InterviewView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView, meta: { guestOnly: true } },
    { path: '/register', component: RegisterView, meta: { guestOnly: true } },
    { path: '/forgot-password', component: ForgotPasswordView },
    { path: '/chat', component: ChatView, meta: { requiresAuth: true } },
    { path: '/chat/:id', component: ChatView, meta: { requiresAuth: true } },
    { path: '/interview', component: InterviewView, meta: { requiresAuth: true } },
    { path: '/interview/:id', component: InterviewView, meta: { requiresAuth: true } },
    { path: '/profile', redirect: { path: '/chat', query: { settings: '1' } } },
  ],
})

router.beforeEach((to) => {
  const session = hasSession()
  if (to.meta.requiresAuth && !session) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && session) {
    return { path: '/chat' }
  }
  return true
})

export default router
