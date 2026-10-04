<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const showNav = computed(() => route.name !== 'login')

const roleLabel = { admin: '管理员', worker: '操作工' }
const currentRole = computed(() => roleLabel[auth.user?.role] || auth.user?.role || '')

function logout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div v-if="!showNav">
    <router-view />
  </div>
  <div v-else class="app-shell">
    <header class="topbar">
      <div class="topbar-brand">
        <span class="mark">帆</span>
        <strong>SailCloth</strong>
        <small>浸渍防水台</small>
      </div>
      <nav class="topbar-nav">
        <router-link to="/">晾晒架</router-link>
        <router-link to="/rolls">布卷台账</router-link>
        <router-link to="/dips">浸渍台账</router-link>
      </nav>
      <div class="topbar-user">
        <span class="role-chip" :class="auth.user?.role === 'admin' ? 'role-admin' : 'role-worker'">
          {{ currentRole }}
        </span>
        <span class="topbar-username">{{ auth.user?.username }}</span>
        <button class="linkish" type="button" @click="logout">退出</button>
      </div>
    </header>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>
