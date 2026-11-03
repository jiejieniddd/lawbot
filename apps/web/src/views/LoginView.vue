<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'

const account = ref('')
const password = ref('')
const loading = ref(false)
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

async function onSubmit() {
  loading.value = true
  try {
    await auth.login(account.value, password.value)
    router.push((route.query.redirect as string) || '/chat')
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-shell">
    <aside class="brand-pane" aria-label="LawBot">
      <div class="brand-mark">LawBot</div>
      <p class="brand-line">结构化法律咨询</p>
      <p class="brand-note">冷静、可追溯的问答工作台。回答仅供参考，不构成正式法律意见。</p>
    </aside>
    <section class="form-pane">
      <div class="form-block">
        <h1>登录</h1>
        <p class="lead">使用账号进入咨询工作台</p>
        <el-form class="auth-form" label-position="top" @submit.prevent="onSubmit">
          <el-form-item label="账号">
            <el-input
              v-model="account"
              type="text"
              autocomplete="username"
              size="large"
              placeholder="请输入账号"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="password"
              type="password"
              autocomplete="current-password"
              show-password
              size="large"
            />
          </el-form-item>
          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            size="large"
            class="submit"
          >
            登录
          </el-button>
        </el-form>
        <p class="hint">
          没有账号？
          <router-link to="/register">注册</router-link>
        </p>
        <p class="foot-note">{{ AUTH_FOOTER_DISCLAIMER }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.auth-shell {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-columns: minmax(280px, 0.42fr) minmax(320px, 0.58fr);
  background: var(--bg);
}

.brand-pane {
  background: linear-gradient(
    165deg,
    color-mix(in srgb, var(--color-primary) 88%, #1a2332) 0%,
    var(--color-primary) 55%,
    color-mix(in srgb, var(--color-info) 55%, var(--color-primary)) 100%
  );
  color: #fff;
  padding: clamp(2rem, 6vw, 3.5rem);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.75rem;
  animation: brand-in 0.55s ease-out both;
}

.brand-mark {
  font-family: var(--font-ui);
  font-size: var(--fs-brand);
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.brand-line {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 500;
  opacity: 0.95;
}

.brand-note {
  margin: 0.5rem 0 0;
  max-width: 28ch;
  font-size: var(--fs-small);
  line-height: 1.55;
  opacity: 0.82;
}

.form-pane {
  display: grid;
  place-items: center;
  padding: 2rem 1.25rem;
  background: var(--surface);
}

.form-block {
  width: min(400px, 100%);
}

h1 {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.02em;
}

.lead {
  margin: 0.35rem 0 1.35rem;
  color: var(--muted);
  font-size: var(--fs-small);
}

.submit {
  width: 100%;
  margin-top: 0.25rem;
}

.hint {
  margin-top: 1.1rem;
  color: var(--muted);
  font-size: var(--fs-small);
}

.foot-note {
  margin-top: 1.25rem;
  font-size: var(--fs-fine);
  color: var(--muted);
  line-height: 1.45;
}

@keyframes brand-in {
  from {
    opacity: 0;
    transform: translateX(-12px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .brand-pane {
    animation: none;
  }
}

@media (max-width: 840px) {
  .auth-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
  .brand-pane {
    padding: 1.5rem 1.25rem;
    min-height: auto;
  }
  .brand-note {
    display: none;
  }
}
</style>
