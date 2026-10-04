<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

const lofts = ref([])
const rolls = ref([])
const dips = ref([])
const error = ref('')
const panelError = ref('')
const selectedId = ref(null)
const panelBusy = ref(false)
const coolBusy = ref(false)
const coolFull = ref(false)

const statusLabel = { raw: '原布', dipping: '浸渍中', cured: '已固化' }

const dipForm = reactive({
  startedAt: '',
  resinPct: 28,
  cureHours: '',
  notes: '',
})

function localNow() {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

const selected = computed(() => rolls.value.find((r) => r.id === selectedId.value) || null)

watch(
  [selectedId, () => selected.value?.coolDownFull],
  () => {
    coolFull.value = !!selected.value?.coolDownFull
  }
)

const rollsByLoft = computed(() => {
  return lofts.value.map((loft) => ({
    loft,
    rolls: rolls.value.filter((r) => r.loftId === loft.id),
  }))
})

const selectedDips = computed(() => {
  if (!selectedId.value) return []
  return dips.value.filter((d) => d.rollId === selectedId.value)
})

const recentFeed = computed(() => dips.value.slice(0, 12))

async function load() {
  error.value = ''
  try {
    const [l, r, d] = await Promise.all([
      api.get('/lofts/'),
      api.get('/rolls/'),
      api.get('/dips/'),
    ])
    lofts.value = l.data.results || l.data
    rolls.value = r.data.results || r.data
    dips.value = d.data.results || d.data
  } catch {
    error.value = '晾晒架加载失败'
  }
}

function openRoll(roll) {
  selectedId.value = roll.id
  panelError.value = ''
  dipForm.startedAt = localNow()
  dipForm.resinPct = 28
  dipForm.cureHours = ''
  dipForm.notes = ''
}

function closePanel() {
  selectedId.value = null
  panelError.value = ''
}

async function setStatus(status) {
  if (!selected.value) return
  panelError.value = ''
  panelBusy.value = true
  try {
    if (status === 'raw' && selected.value.status === 'dipping') {
      // 浸渍中拨回原布走专页动作：后端按冷却闸门做条件更新，
      // 未勾 400、并发第二笔 409。
      await api.post(`/rolls/${selected.value.id}/revert_to_raw/`)
    } else {
      await api.patch(`/rolls/${selected.value.id}/`, { status })
    }
    await load()
  } catch (e) {
    const data = e.response?.data
    panelError.value =
      data?.status?.[0] ||
      data?.detail ||
      '状态更新失败（标「已固化」需最近浸渍固化时长 ≥ 12 小时；浸渍中拨回原布需先勾选冷却已满）'
  } finally {
    panelBusy.value = false
  }
}

async function toggleCoolDown(full) {
  if (!selected.value || !isAdmin.value) return
  panelError.value = ''
  coolBusy.value = true
  // 先乐观更新；失败或非预期响应时回退到服务端值。
  const previous = coolFull.value
  coolFull.value = full
  try {
    const { data } = await api.post(
      `/rolls/${selected.value.id}/set_cool_down/`,
      { full }
    )
    const idx = rolls.value.findIndex((r) => r.id === data.id)
    if (idx !== -1) rolls.value[idx] = data
    coolFull.value = !!data.coolDownFull
  } catch (e) {
    coolFull.value = previous
    const data = e.response?.data
    panelError.value =
      data?.full?.[0] || data?.detail || '冷却确认失败'
  } finally {
    coolBusy.value = false
  }
}

async function logDip() {
  if (!selected.value) return
  panelError.value = ''
  panelBusy.value = true
  try {
    // 冷却不拦浸渍登记；原布登记浸渍后由后端自动转为浸渍中并重置冷却勾选。
    await api.post('/dips/', {
      rollId: selected.value.id,
      startedAt: new Date(dipForm.startedAt).toISOString(),
      resinPct: dipForm.resinPct,
      cureHours:
        dipForm.cureHours === '' || dipForm.cureHours === null
          ? null
          : dipForm.cureHours,
      notes: dipForm.notes,
    })
    dipForm.cureHours = ''
    dipForm.notes = ''
    dipForm.startedAt = localNow()
    await load()
  } catch (e) {
    panelError.value =
      e.response?.data?.detail ||
      JSON.stringify(e.response?.data) ||
      '登记浸渍失败'
  } finally {
    panelBusy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="rack-page">
    <header class="rack-head">
      <div>
        <h1>帆布间晾晒架</h1>
        <p class="sub">按帆布间挂卷；点选布卷登记浸渍或标固化。固化规则：最近浸渍时长 ≥ 12 小时。浸渍中卷须由管理员在专页勾选「冷却已满」方可拨回原布。</p>
      </div>
      <button class="btn secondary" type="button" @click="load">刷新架面</button>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="rack-floor">
      <section
        v-for="group in rollsByLoft"
        :key="group.loft.id"
        class="loft-bay"
      >
        <div class="bay-rail">
          <span class="bay-name">{{ group.loft.name }}</span>
          <span class="bay-meta">{{ group.loft.location || '工位' }} · {{ group.rolls.length }} 卷</span>
        </div>
        <div class="peg-row">
          <button
            v-for="roll in group.rolls"
            :key="roll.id"
            type="button"
            class="roll-chip"
            :class="[
              'chip-' + roll.status,
              { 'is-selected': selectedId === roll.id },
              { 'cool-ok': roll.status === 'dipping' && roll.coolDownFull },
            ]"
            @click="openRoll(roll)"
          >
            <span class="peg" aria-hidden="true" />
            <span class="hang-tag" :class="'tag-' + roll.status">
              {{ statusLabel[roll.status] || roll.status }}
            </span>
            <span v-if="roll.status === 'dipping' && roll.coolDownFull" class="cool-dot" title="冷却已满">凉</span>
            <span class="chip-code">{{ roll.rollCode }}</span>
            <span class="chip-gsm">{{ roll.fabricWeightGsm }} gsm</span>
          </button>
          <p v-if="!group.rolls.length" class="empty-bay">此间暂无布卷</p>
        </div>
      </section>
      <p v-if="!lofts.length && !error" class="hint">尚无帆布间数据</p>
    </div>

    <section class="dip-feed panel">
      <h2 class="feed-title">浸渍流水</h2>
      <p class="hint" style="margin: 0 0 12px">架下次要信息流；主操作在右侧布卷面板完成。</p>
      <ul v-if="recentFeed.length" class="feed-list">
        <li v-for="row in recentFeed" :key="row.id">
          <strong>{{ row.rollCode }}</strong>
          <span class="feed-loft">{{ row.loftName }}</span>
          <span>{{ new Date(row.startedAt).toLocaleString() }}</span>
          <span>树脂 {{ row.resinPct }}%</span>
          <span>固化 {{ row.cureHours ?? '—' }} h</span>
        </li>
      </ul>
      <p v-else class="hint" style="margin:0">暂无浸渍记录</p>
    </section>

    <div
      v-if="selected"
      class="drawer-backdrop"
      @click.self="closePanel"
    />
    <aside v-if="selected" class="roll-drawer" aria-label="布卷操作">
      <header class="drawer-head">
        <div>
          <p class="drawer-kicker">{{ selected.loftName }}</p>
          <h2>{{ selected.rollCode }}</h2>
        </div>
        <button class="btn secondary" type="button" @click="closePanel">关闭</button>
      </header>

      <div class="drawer-status">
        <span class="hang-tag" :class="'tag-' + selected.status">
          {{ statusLabel[selected.status] }}
        </span>
        <span class="hint">{{ selected.fabricWeightGsm }} gsm</span>
      </div>
      <p v-if="selected.notes" class="hint">{{ selected.notes }}</p>

      <!-- 冷却闸门：仅浸渍中显示；已固化不看此勾。管理员可勾，操作工只读。 -->
      <div v-if="selected.status === 'dipping'" class="drawer-cooldown panel">
        <label class="checkline">
          <input
            v-model="coolFull"
            type="checkbox"
            :disabled="!isAdmin || panelBusy || coolBusy"
            @change="toggleCoolDown($event.target.checked)"
          />
          <span>冷却已满</span>
        </label>
        <p class="hint" style="margin:0">
          <template v-if="isAdmin">勾选确认冷却已满后，方可把该卷拨回原布；再次登记浸渍将重置此勾选。</template>
          <template v-else>冷却确认仅管理员可操作；冷却未满时拨回原布会被拒绝。</template>
        </p>
      </div>

      <p v-if="panelError" class="error">{{ panelError }}</p>

      <div class="drawer-actions">
        <button
          class="btn secondary"
          type="button"
          :disabled="panelBusy || selected.status === 'raw'"
          :title="selected.status === 'dipping' && !selected.coolDownFull ? '冷却未满，拨回将被拒绝' : ''"
          @click="setStatus('raw')"
        >
          标为原布
        </button>
        <button
          class="btn secondary"
          type="button"
          :disabled="panelBusy || selected.status === 'dipping'"
          @click="setStatus('dipping')"
        >
          标为浸渍中
        </button>
        <button
          class="btn"
          type="button"
          :disabled="panelBusy || selected.status === 'cured'"
          @click="setStatus('cured')"
        >
          标为已固化
        </button>
      </div>

      <form class="drawer-form" @submit.prevent="logDip">
        <h3>登记浸渍</h3>
        <label>开始时间
          <input v-model="dipForm.startedAt" type="datetime-local" required />
        </label>
        <label>树脂 %
          <input v-model.number="dipForm.resinPct" type="number" step="0.1" required />
        </label>
        <label>固化时长 h（可空）
          <input v-model="dipForm.cureHours" type="number" step="0.1" />
        </label>
        <label>备注
          <input v-model="dipForm.notes" />
        </label>
        <button class="btn" type="submit" :disabled="panelBusy">写入浸渍记录</button>
      </form>

      <div class="drawer-history">
        <h3>本卷浸渍</h3>
        <ul v-if="selectedDips.length" class="feed-list compact">
          <li v-for="row in selectedDips" :key="row.id">
            <span>{{ new Date(row.startedAt).toLocaleString() }}</span>
            <span>{{ row.resinPct }}%</span>
            <span>{{ row.cureHours ?? '—' }} h</span>
          </li>
        </ul>
        <p v-else class="hint" style="margin:0">本卷尚无浸渍</p>
      </div>
    </aside>
  </div>
</template>
