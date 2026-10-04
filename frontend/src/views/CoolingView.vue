<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

const rolls = ref([])
const error = ref('')
const busyId = ref(null)

const statusLabel = { raw: '原布', dipping: '浸渍中', cured: '已固化' }

const dippingRolls = computed(() => rolls.value.filter((r) => r.status === 'dipping'))
const otherRolls = computed(() => rolls.value.filter((r) => r.status !== 'dipping'))

async function load() {
  error.value = ''
  try {
    const { data } = await api.get('/rolls/')
    rolls.value = data.results || data
  } catch {
    error.value = '冷却勾专页加载失败'
  }
}

function canEdit(roll) {
  return isAdmin.value && roll.status === 'dipping'
}

async function onToggle(roll, event) {
  const checked = event.target.checked
  busyId.value = roll.id
  error.value = ''
  try {
    const { data } = await api.patch(`/rolls/${roll.id}/`, { coolingDone: checked })
    const idx = rolls.value.findIndex((r) => r.id === roll.id)
    if (idx !== -1) rolls.value[idx] = data
  } catch (e) {
    event.target.checked = !checked
    error.value =
      e.response?.data?.detail ||
      e.response?.data?.coolingDone?.[0] ||
      '冷却勾选失败（仅管理员可勾选）'
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1>冷却勾专页</h1>
    <p class="sub">
      浸渍中的布卷须在此勾「冷却已满」后，才能在晾晒架面板拨回原布；标「已固化」不看这勾。
      <template v-if="isAdmin">当前为管理员，可勾选。</template>
      <template v-else>操作工仅可查看，勾选需管理员。</template>
    </p>
    <p v-if="error" class="error">{{ error }}</p>

    <section class="panel">
      <h2 class="feed-title">浸渍中 · 待冷却</h2>
      <table v-if="dippingRolls.length">
        <thead>
          <tr>
            <th>帆布间</th>
            <th>卷号</th>
            <th>状态</th>
            <th>冷却已满</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="roll in dippingRolls" :key="roll.id">
            <td>{{ roll.loftName }}</td>
            <td>{{ roll.rollCode }}</td>
            <td>
              <span class="badge" :class="'badge-' + roll.status">
                {{ statusLabel[roll.status] || roll.status }}
              </span>
            </td>
            <td>
              <label class="cooling-check">
                <input
                  type="checkbox"
                  :checked="roll.coolingDone"
                  :disabled="!canEdit(roll) || busyId === roll.id"
                  @change="onToggle(roll, $event)"
                />
                <span>{{ roll.coolingDone ? '已满' : '未满' }}</span>
              </label>
            </td>
            <td class="hint">
              {{ roll.coolingDone ? '已勾已满，可拨回原布' : '未勾已满，拨回原布将被拒绝' }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="hint" style="margin:0">暂无浸渍中的布卷</p>
    </section>

    <section class="panel">
      <h2 class="feed-title">其余布卷（冷却勾不约束）</h2>
      <table v-if="otherRolls.length">
        <thead>
          <tr>
            <th>帆布间</th>
            <th>卷号</th>
            <th>状态</th>
            <th>冷却已满</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="roll in otherRolls" :key="roll.id">
            <td>{{ roll.loftName }}</td>
            <td>{{ roll.rollCode }}</td>
            <td>
              <span class="badge" :class="'badge-' + roll.status">
                {{ statusLabel[roll.status] || roll.status }}
              </span>
            </td>
            <td>
              <label class="cooling-check">
                <input type="checkbox" :checked="roll.coolingDone" disabled />
                <span>{{ roll.coolingDone ? '已满' : '未满' }}</span>
              </label>
            </td>
            <td class="hint">
              {{ roll.status === 'cured' ? '已固化不看这勾' : '未在浸渍，入浸后重新计时' }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="hint" style="margin:0">暂无其他布卷</p>
    </section>
  </div>
</template>
