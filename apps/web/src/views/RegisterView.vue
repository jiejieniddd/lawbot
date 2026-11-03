<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'

const account = ref('')
const password = ref('')
const displayName = ref('')
const loading = ref(false)
const auth = useAuthStore()
const router = useRouter()

async function onSubmit() {
  loading.value = true
  try {
    await auth.register(account.value, password.value, displayName.value || undefined)
    router.push('/chat')
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
      <p class="brand-note">创建账号后即可开始会话。我们重视可追溯引用与清晰免责说明。</p>
    </aside>
    <section class="form-pane">
      <div class="form-block">
        <h1>注册</h1>
        <p class="lead">创建账号并进入咨询工作台</p>
        <el-form class="auth-form" label-position="top" @submit.prevent="onSubmit">
          <el-form-item label="昵称">
            <el-input v-model="displayName" size="large" placeholder="可选" />
          </el-form-item>
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
              autocomplete="new-password"
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
            注册并进入
          </el-button>
        </el-form>
        <p class="hint">
          已有账号？
          <router-link to="/login">登录</router-link>
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

@media (max-width: 840px) {
  .auth-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
  .brand-pane {
    padding: 1.5rem 1.25rem;
  }
  .brand-note {
    display: none;
  }
}
</style>
