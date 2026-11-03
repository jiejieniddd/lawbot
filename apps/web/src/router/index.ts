import { createRouter, createWebHistory } from 'vue-router'
import { hasSession } from '../api/client'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import ChatView from '../views/ChatView.vue'
import ProfileView from '../views/ProfileView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView, meta: { guestOnly: true } },
    { path: '/register', component: RegisterView, meta: { guestOnly: true } },
    { path: '/chat', component: ChatView, meta: { requiresAuth: true } },
    { path: '/chat/:id', component: ChatView, meta: { requiresAuth: true } },
    { path: '/profile', component: ProfileView, meta: { requiresAuth: true } },
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
