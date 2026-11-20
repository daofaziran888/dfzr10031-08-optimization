<template>
  <section class="page" data-module="basket_analysis">
    <header class="page-head">
      <div>
        <h2>同单连带分析</h2>
        <p class="page-desc">
          面向类目经理的购物篮取数与联购分析：按已复核退款恢复净件数，以有效订单计算类目同单次数、
          提升倍数与样本规模，并对季节性套装展开成分做来源更正。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="openLineImport">导入订单行</button>
        <button class="btn" type="button" @click="openRefundImport">补交退款明细</button>
        <button class="btn primary" type="button" @click="recompute">按更正口径重算</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="filter-bar">
      <label class="filter-item">
        <span>分析版本（图表 CHAR-0004 同单连带联购矩阵读取同单连带分析表）</span>
        <select v-model="selectedRun" @change="loadVersion">
          <option value="">最新版本</option>
          <option v-for="r in runs" :key="r.分析编号" :value="r.分析编号">
            {{ r.分析编号 }} · 样本 {{ r.样本规模 }} · {{ r.备注 }}
          </option>
        </select>
      </label>
      <button class="btn" type="button" @click="loadAll">刷新</button>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </div>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="['tab-btn', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </nav>

    <!-- 联购矩阵 -->
    <div v-if="activeTab === 'matrix'">
      <p class="page-desc">
        每格展示提升倍数（实际同单率 / 独立假设期望同单率）、同单次数与套装剔除数；
        点击非对角格可查看该分值对应的订单集合及其来源。
      </p>
      <div class="matrix-wrap">
        <table class="matrix-table">
          <thead>
            <tr>
              <th class="matrix-corner">类目 × 类目</th>
              <th v-for="c in categories" :key="c" class="matrix-head">{{ c }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rowCat in categories" :key="rowCat">
              <th class="matrix-row-head">{{ rowCat }}</th>
              <td
                v-for="colCat in categories"
                :key="colCat"
                :class="['matrix-cell', { clickable: rowCat !== colCat }]"
                :style="cellStyle(rowCat, colCat)"
                :title="cellTitle(rowCat, colCat)"
                @click="rowCat !== colCat && openPair(rowCat, colCat)"
              >
                <template v-if="cellMap[cellKey(rowCat, colCat)]">
                  <template v-if="rowCat === colCat">
                    <strong class="lift-text">基准</strong>
                    <span class="cell-meta">单数 {{ cellMap[cellKey(rowCat, colCat)].类目A单数 }}</span>
                  </template>
                  <template v-else>
                    <strong class="lift-text">{{ formatLift(cellMap[cellKey(rowCat, colCat)].提升倍数) }}</strong>
                    <span class="cell-meta">同单 {{ cellMap[cellKey(rowCat, colCat)].同单次数 }}</span>
                    <span v-if="cellMap[cellKey(rowCat, colCat)].剔除数" class="exclude-badge">
                      剔 {{ cellMap[cellKey(rowCat, colCat)].剔除数 }}
                    </span>
                  </template>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="page-desc">
        样本规模 N = {{ currentRun?.样本规模 ?? '—' }} 个有效订单；色阶越深提升倍数越高，
        「剔 N」表示因纯同套装展开而被剔除的订单数。
      </p>
    </div>

    <!-- 有效购物篮 -->
    <div v-if="activeTab === 'basket'">
      <table class="data-table">
        <thead>
          <tr>
            <th>订单编号</th>
            <th>有效类目（同单同类目多行只贡献一次）</th>
            <th>类目来源</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in baskets" :key="b.订单编号">
            <td>{{ b.订单编号 }}</td>
            <td>{{ b.有效类目 }}</td>
            <td class="source-cell">
              <span v-for="(src, cat) in b.类目来源" :key="cat" class="source-tag">
                {{ cat }}：{{ src.source_types.join('、')
                }}<template v-if="src.bundle_ids.length">（套装 {{ src.bundle_ids.join('、') }}）</template>
              </span>
            </td>
          </tr>
          <tr v-if="!baskets.length">
            <td colspan="3" class="empty-state">暂无有效购物篮，请先重算联购记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 订单行净件数 -->
    <div v-if="activeTab === 'lines'">
      <table class="data-table">
        <thead>
          <tr>
            <th>订单编号</th>
            <th>订单行</th>
            <th>商品类目</th>
            <th>行状态</th>
            <th>来源类型</th>
            <th>实际件数</th>
            <th>已复核退款</th>
            <th>净件数</th>
            <th>是否计入</th>
            <th>移出原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in lineDetails" :key="`${d.订单编号}-${d.订单行编号}`">
            <td>{{ d.订单编号 }}</td>
            <td>{{ d.订单行编号 }}</td>
            <td>{{ d.商品类目 }}</td>
            <td>{{ d.订单行状态 }}</td>
            <td>{{ d.来源类型 }}</td>
            <td>{{ d.实际件数 }}</td>
            <td>{{ d.已退款件数 }}</td>
            <td :class="d.净件数 === 0 ? 'zero-text' : ''">{{ d.净件数 }}</td>
            <td>
              <span :class="d.是否计入购物篮 ? 'ok-text' : 'zero-text'">
                {{ d.是否计入购物篮 ? '计入' : '移出' }}
              </span>
            </td>
            <td>{{ d.移出原因 || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 退款明细 -->
    <div v-if="activeTab === 'refunds'">
      <table class="data-table">
        <thead>
          <tr>
            <th>退款编号</th>
            <th>订单编号</th>
            <th>订单行</th>
            <th>关联类目</th>
            <th>退款件数</th>
            <th>复核状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rf in refunds" :key="rf.退款编号">
            <td>{{ rf.退款编号 }}</td>
            <td>{{ rf.订单编号 }}</td>
            <td>{{ rf.订单行编号 }}</td>
            <td>{{ rf.关联类目 }}</td>
            <td>{{ rf.退款件数 }}</td>
            <td>
              <span :class="rf.复核状态 === '已复核' ? 'ok-text' : 'warn-text'">{{ rf.复核状态 }}</span>
            </td>
            <td>
              <button
                v-if="rf.复核状态 !== '已复核'"
                class="link"
                type="button"
                @click="reviewRefund(rf.id)"
              >
                复核通过
              </button>
              <span v-else class="page-desc">已参与净件数恢复</span>
            </td>
          </tr>
          <tr v-if="!refunds.length">
            <td colspan="7" class="empty-state">暂无退款明细</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分析版本 -->
    <div v-if="activeTab === 'runs'">
      <table class="data-table">
        <thead>
          <tr>
            <th>分析编号</th>
            <th>样本规模</th>
            <th>类目数量</th>
            <th>无效行数</th>
            <th>归零移出行数</th>
            <th>待复核退款</th>
            <th>已复核退款</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.分析编号">
            <td>{{ r.分析编号 }}</td>
            <td>{{ r.样本规模 }}</td>
            <td>{{ r.类目数量 }}</td>
            <td>{{ r.无效行数 }}</td>
            <td>{{ r.归零移出行数 }}</td>
            <td>{{ r.待复核退款数 }}</td>
            <td>{{ r.已复核退款数 }}</td>
            <td>{{ r.备注 }}</td>
          </tr>
          <tr v-if="!runs.length">
            <td colspan="8" class="empty-state">尚未生成联购记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span>口径：净件数 = 实际件数 − 已复核退款；净件数归零才从该单移出，部分退款保留</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 订单行导入 -->
    <Teleport to="body">
      <div v-if="showLineModal" class="modal-overlay" @click.self="showLineModal = false">
        <div class="modal-card wide">
          <header class="modal-head">
            <h3>购物篮取数：导入订单行</h3>
            <button class="btn ghost" type="button" @click="showLineModal = false">&times;</button>
          </header>
          <div class="modal-body">
            <p class="page-desc">业务键为 订单编号+订单行编号，重复导入整行覆盖，不会重复计单。</p>
            <table class="data-table import-table">
              <thead>
                <tr>
                  <th>订单编号</th><th>订单行编号</th><th>商品类目</th><th>行状态</th>
                  <th>实际件数</th><th>来源类型</th><th>套装编号</th><th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in lineDraft" :key="idx">
                  <td><input v-model="row.订单编号" placeholder="SO-1001" /></td>
                  <td><input v-model="row.订单行编号" placeholder="L01" /></td>
                  <td><input v-model="row.商品类目" placeholder="运动鞋" /></td>
                  <td>
                    <select v-model="row.订单行状态">
                      <option>正常</option>
                      <option>已取消</option>
                      <option>已关闭</option>
                    </select>
                  </td>
                  <td><input v-model.number="row.实际件数" type="number" min="0" /></td>
                  <td>
                    <select v-model="row.来源类型">
                      <option>原始订单行</option>
                      <option>套装主行</option>
                      <option>套装展开成分</option>
                    </select>
                  </td>
                  <td><input v-model="row.套装编号" placeholder="可空" /></td>
                  <td><button class="link" type="button" @click="lineDraft.splice(idx, 1)">删除</button></td>
                </tr>
              </tbody>
            </table>
            <button class="btn" type="button" @click="addLineDraft">+ 增加一行</button>
          </div>
          <footer class="modal-foot">
            <button class="btn" type="button" @click="fillLineSample">填入套装示例</button>
            <button class="btn" type="button" @click="showLineModal = false">取消</button>
            <button class="btn primary" type="button" @click="submitLineImport">提交导入</button>
          </footer>
        </div>
      </div>
    </Teleport>

    <!-- 退款导入 -->
    <Teleport to="body">
      <div v-if="showRefundModal" class="modal-overlay" @click.self="showRefundModal = false">
        <div class="modal-card wide">
          <header class="modal-head">
            <h3>补交退款明细（关联原订单行）</h3>
            <button class="btn ghost" type="button" @click="showRefundModal = false">&times;</button>
          </header>
          <div class="modal-body">
            <p class="page-desc">只有「已复核」退款参与净件数恢复；待复核退款复核后重算才生效。</p>
            <table class="data-table import-table">
              <thead>
                <tr>
                  <th>退款编号</th><th>订单编号</th><th>订单行编号</th><th>退款件数</th><th>复核状态</th><th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in refundDraft" :key="idx">
                  <td><input v-model="row.退款编号" placeholder="RF-1001" /></td>
                  <td><input v-model="row.订单编号" placeholder="SO-1008" /></td>
                  <td><input v-model="row.订单行编号" placeholder="L01" /></td>
                  <td><input v-model.number="row.退款件数" type="number" min="0" /></td>
                  <td>
                    <select v-model="row.复核状态">
                      <option>待复核</option>
                      <option>已复核</option>
                    </select>
                  </td>
                  <td><button class="link" type="button" @click="refundDraft.splice(idx, 1)">删除</button></td>
                </tr>
              </tbody>
            </table>
            <button class="btn" type="button" @click="addRefundDraft">+ 增加一条</button>
          </div>
          <footer class="modal-foot">
            <button class="btn" type="button" @click="showRefundModal = false">取消</button>
            <button class="btn primary" type="button" @click="submitRefundImport">提交导入</button>
          </footer>
        </div>
      </div>
    </Teleport>

    <!-- 单元格钻取：联合订单及其来源 -->
    <Teleport to="body">
      <div v-if="pairModal.visible" class="modal-overlay" @click.self="pairModal.visible = false">
        <div class="modal-card wide">
          <header class="modal-head">
            <h3>{{ pairModal.catA }} × {{ pairModal.catB }} 的联购订单集合</h3>
            <button class="btn ghost" type="button" @click="pairModal.visible = false">&times;</button>
          </header>
          <div class="modal-body" v-if="pairModal.data">
            <div class="stat-row">
              <article class="stat-card">
                <span class="stat-label">提升倍数</span>
                <strong class="stat-value">{{ formatLift(pairModal.data.cell.提升倍数) }}</strong>
              </article>
              <article class="stat-card">
                <span class="stat-label">同单次数</span>
                <strong class="stat-value">{{ pairModal.data.cell.同单次数 }}</strong>
              </article>
              <article class="stat-card">
                <span class="stat-label">套装剔除数</span>
                <strong class="stat-value">{{ pairModal.data.cell.剔除数 }}</strong>
              </article>
              <article class="stat-card">
                <span class="stat-label">可比样本量 N</span>
                <strong class="stat-value">{{ pairModal.data.cell.样本规模 }}</strong>
              </article>
            </div>
            <h4>联合订单（有效购物篮核对）</h4>
            <table class="data-table">
              <thead>
                <tr><th>订单编号</th><th>有效类目</th><th>类目来源</th></tr>
              </thead>
              <tbody>
                <tr v-for="b in pairModal.data.baskets" :key="b.订单编号">
                  <td>{{ b.订单编号 }}</td>
                  <td>{{ b.有效类目 }}</td>
                  <td class="source-cell">
                    <span v-for="(src, cat) in b.类目来源" :key="cat" class="source-tag">
                      {{ cat }}：{{ src.source_types.join('、')
                      }}<template v-if="src.bundle_ids.length">（套装 {{ src.bundle_ids.join('、') }}）</template>
                    </span>
                  </td>
                </tr>
                <tr v-if="!pairModal.data.baskets.length">
                  <td colspan="3" class="empty-state">没有同单订单</td>
                </tr>
              </tbody>
            </table>
            <template v-if="pairModal.data.excluded_orders?.length">
              <h4>被剔除的订单（纯同套装展开，不计入成分连带）</h4>
              <table class="data-table">
                <thead><tr><th>订单编号</th><th>套装编号</th></tr></thead>
                <tbody>
                  <tr v-for="e in pairModal.data.excluded_orders" :key="e.订单编号">
                    <td>{{ e.订单编号 }}</td>
                    <td>{{ e.套装编号 }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

const ENDPOINT = '/api/basket_analysis'

interface CategorySource {
  source_types: string[]
  bundle_ids: string[]
  lines: string[]
}
interface ExcludedOrder {
  订单编号: string
  套装编号: string
}
interface Cell {
  id: number
  分析编号: string
  类目A: string
  类目B: string
  类目A单数: number
  类目B单数: number
  同单次数: number
  剔除数: number
  提升倍数: number | null
  样本规模: number
  联合订单: string[]
  剔除明细: ExcludedOrder[]
}
interface Basket {
  id: number
  分析编号: string
  订单编号: string
  有效类目: string
  类目来源: Record<string, CategorySource>
}
interface LineDetail {
  订单编号: string
  订单行编号: string
  商品类目: string
  商品名称: string
  订单行状态: string
  来源类型: string
  套装编号: string
  实际件数: number
  已退款件数: number
  净件数: number
  是否计入购物篮: boolean
  移出原因: string
}
interface RefundRow {
  id: number
  退款编号: string
  订单编号: string
  订单行编号: string
  关联类目: string
  退款件数: number
  复核状态: string
}
interface RunRow {
  id: number
  分析编号: string
  样本规模: number
  类目数量: number
  无效行数: number
  归零移出行数: number
  待复核退款数: number
  已复核退款数: number
  备注: string
}
interface PairData {
  cell: Cell
  baskets: Basket[]
  excluded_orders: ExcludedOrder[]
}

const tabs = [
  { key: 'matrix', label: '联购矩阵' },
  { key: 'basket', label: '有效购物篮' },
  { key: 'lines', label: '订单行净件数' },
  { key: 'refunds', label: '退款明细' },
  { key: 'runs', label: '分析版本' },
] as const

const activeTab = ref<string>('matrix')
const categories = ref<string[]>([])
const cells = ref<Cell[]>([])
const baskets = ref<Basket[]>([])
const lineDetails = ref<LineDetail[]>([])
const refunds = ref<RefundRow[]>([])
const runs = ref<RunRow[]>([])
const currentRun = ref<RunRow | null>(null)
const selectedRun = ref('')
const message = ref('')
const messageOk = ref(true)

const showLineModal = ref(false)
const showRefundModal = ref(false)
const lineDraft = ref<Record<string, string | number>[]>([])
const refundDraft = ref<Record<string, string | number>[]>([])
const pairModal = reactive<{ visible: boolean; catA: string; catB: string; data: PairData | null }>({
  visible: false,
  catA: '',
  catB: '',
  data: null,
})

const cellMap = ref<Record<string, Cell>>({})

const stats = ref([
  { label: '有效订单样本 N', value: 0 },
  { label: '分析类目数', value: 0 },
  { label: '待复核退款', value: 0 },
  { label: '套装剔除（上衣×裤子）', value: 0 },
])

function cellKey(a: string, b: string) {
  return `${a}||${b}`
}

function cellStyle(rowCat: string, colCat: string) {
  const c = cellMap.value[cellKey(rowCat, colCat)]
  if (!c || rowCat === colCat) return { background: '#f1f5f9' }
  const lift = Number(c.提升倍数 ?? 0)
  const alpha = Math.min(Math.max((lift - 0.5) / 2, 0.06), 0.85)
  return { background: `rgba(31, 111, 235, ${alpha.toFixed(3)})`, color: alpha > 0.45 ? '#fff' : '#1f2937' }
}

function formatLift(v: number | null) {
  return v === null || v === undefined ? '—' : `${Number(v).toFixed(2)}×`
}

function cellTitle(rowCat: string, colCat: string) {
  const c = cellMap.value[cellKey(rowCat, colCat)]
  if (!c) return ''
  if (rowCat === colCat) {
    return `${rowCat} 单独出现 ${c.类目A单数} 单 · 可比样本量 N=${c.样本规模}`
  }
  return `${rowCat}×${colCat}：提升 ${formatLift(c.提升倍数)} · 同单 ${c.同单次数} 单 · 剔除 ${c.剔除数} 单 · 可比样本量 N=${c.样本规模}`
}

function notify(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function loadAll() {
  try {
    const [matrixData, basketData, lineData, refundData, runData] = await Promise.all([
      fetchJson<any>(`${ENDPOINT}/matrix${selectedRun.value ? `?run_no=${encodeURIComponent(selectedRun.value)}` : ''}`).catch(() => null),
      fetchJson<any>(`${ENDPOINT}/baskets${selectedRun.value ? `?run_no=${encodeURIComponent(selectedRun.value)}` : ''}`),
      fetchJson<any>(`${ENDPOINT}/line_details`),
      fetchJson<any>(`${ENDPOINT}/refunds`),
      fetchJson<any>(`${ENDPOINT}/runs`),
    ])
    runs.value = runData.items ?? []
    refunds.value = refundData.items ?? []
    lineDetails.value = lineData.items ?? []
    if (matrixData) {
      currentRun.value = matrixData.run
      categories.value = matrixData.categories ?? []
      cells.value = matrixData.cells ?? []
      cellMap.value = Object.fromEntries(cells.value.map((c) => [cellKey(String(c.类目A), String(c.类目B)), c]))
      baskets.value = basketData.items ?? []
      const tp = cells.value.find((c) => c.类目A === '上衣' && c.类目B === '裤子')
      stats.value = [
        { label: '有效订单样本 N', value: Number(currentRun.value?.样本规模 ?? 0) },
        { label: '分析类目数', value: categories.value.length },
        { label: '待复核退款', value: Number(runData.items?.[0]?.待复核退款数 ?? 0) },
        { label: '套装剔除（上衣×裤子）', value: Number(tp?.剔除数 ?? 0) },
      ]
    } else {
      currentRun.value = null
      categories.value = []
      cells.value = []
      cellMap.value = {}
      baskets.value = []
      stats.value[0].value = 0
      stats.value[1].value = 0
    }
  } catch (error) {
    notify(error instanceof Error ? error.message : '数据加载失败', false)
  }
}

function loadVersion() {
  void loadAll()
}

async function recompute() {
  try {
    const res = await request(`${ENDPOINT}/recompute`, {
      method: 'POST',
      body: JSON.stringify({ remark: '前端触发按更正口径重算' }),
    })
    const data = await res.json()
    if (!res.ok || data.ok === false) throw new Error(data.message || '重算失败')
    selectedRun.value = ''
    notify(data.message || '重算完成')
    await loadAll()
  } catch (error) {
    notify(error instanceof Error ? error.message : '重算失败', false)
  }
}

async function reviewRefund(id: number) {
  try {
    const res = await request(`${ENDPOINT}/refunds/${id}/review`, { method: 'POST' })
    const data = await res.json()
    if (!res.ok || data.ok === false) throw new Error(data.message || '复核失败')
    notify(data.message || '退款已复核，请重算联购记录')
    await loadAll()
  } catch (error) {
    notify(error instanceof Error ? error.message : '复核失败', false)
  }
}

function openLineImport() {
  lineDraft.value = [emptyLine()]
  showLineModal.value = true
}

function emptyLine() {
  return {
    订单编号: '',
    订单行编号: '',
    商品类目: '',
    订单行状态: '正常',
    实际件数: 1,
    来源类型: '原始订单行',
    套装编号: '',
  }
}

function addLineDraft() {
  lineDraft.value.push(emptyLine())
}

function fillLineSample() {
  lineDraft.value = [
    { 订单编号: 'SO-1011', 订单行编号: 'L01', 商品类目: '季节性套装', 订单行状态: '正常', 实际件数: 1, 来源类型: '套装主行', 套装编号: 'BD-02' },
    { 订单编号: 'SO-1011', 订单行编号: 'L02', 商品类目: '上衣', 订单行状态: '正常', 实际件数: 1, 来源类型: '套装展开成分', 套装编号: 'BD-02' },
    { 订单编号: 'SO-1011', 订单行编号: 'L03', 商品类目: '裤子', 订单行状态: '正常', 实际件数: 1, 来源类型: '套装展开成分', 套装编号: 'BD-02' },
  ]
}

async function submitLineImport() {
  try {
    const res = await request(`${ENDPOINT}/lines/import`, {
      method: 'POST',
      body: JSON.stringify({ lines: lineDraft.value }),
    })
    const data = await res.json()
    if (!res.ok || data.ok === false) {
      throw new Error(`${data.message ?? '导入失败'}：${(data.errors ?? []).join('；')}`)
    }
    showLineModal.value = false
    notify(data.message)
    await loadAll()
  } catch (error) {
    notify(error instanceof Error ? error.message : '导入失败', false)
  }
}

function openRefundImport() {
  refundDraft.value = [{ 退款编号: '', 订单编号: '', 订单行编号: '', 退款件数: 1, 复核状态: '待复核' }]
  showRefundModal.value = true
}

function addRefundDraft() {
  refundDraft.value.push({ 退款编号: '', 订单编号: '', 订单行编号: '', 退款件数: 1, 复核状态: '待复核' })
}

async function submitRefundImport() {
  try {
    const res = await request(`${ENDPOINT}/refunds/import`, {
      method: 'POST',
      body: JSON.stringify({ refunds: refundDraft.value }),
    })
    const data = await res.json()
    if (!res.ok || data.ok === false) {
      throw new Error(`${data.message ?? '导入失败'}：${(data.errors ?? []).join('；')}`)
    }
    showRefundModal.value = false
    notify(data.message)
    await loadAll()
  } catch (error) {
    notify(error instanceof Error ? error.message : '导入失败', false)
  }
}

async function openPair(catA: string, catB: string) {
  try {
    const params = new URLSearchParams({ cat_a: catA, cat_b: catB })
    if (selectedRun.value) params.set('run_no', selectedRun.value)
    pairModal.data = await fetchJson<any>(`${ENDPOINT}/pair?${params.toString()}`)
    pairModal.catA = catA
    pairModal.catB = catB
    pairModal.visible = true
  } catch (error) {
    notify(error instanceof Error ? error.message : '联合订单查询失败', false)
  }
}

onMounted(loadAll)
</script>

<style scoped>
.tab-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.tab-btn { border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
.tab-btn.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.matrix-wrap { overflow-x: auto; background: #fff; border: 1px solid var(--border); border-radius: 8px; }
.matrix-table { border-collapse: collapse; min-width: 560px; }
.matrix-corner, .matrix-head, .matrix-row-head {
  background: #f8fafc; border: 1px solid var(--border); padding: 10px; font-size: 13px; text-align: center;
}
.matrix-row-head { text-align: left; white-space: nowrap; }
.matrix-cell {
  border: 1px solid var(--border); min-width: 108px; padding: 8px 10px; text-align: center; vertical-align: middle;
}
.matrix-cell.clickable { cursor: pointer; }
.matrix-cell.clickable:hover { outline: 2px solid var(--brand); outline-offset: -2px; }
.lift-text { display: block; font-size: 15px; }
.cell-meta { display: block; font-size: 12px; opacity: 0.85; }
.exclude-badge {
  display: inline-block; margin-top: 2px; padding: 0 6px; border-radius: 10px;
  background: #fef3c7; color: #92400e; font-size: 11px;
}
.source-cell { display: flex; flex-wrap: wrap; gap: 6px; }
.source-tag { background: #eef2ff; color: #3730a3; border-radius: 4px; padding: 2px 6px; font-size: 12px; }
.ok-text { color: #047857; }
.warn-text { color: #b45309; }
.zero-text { color: #b42318; font-weight: 600; }
.modal-card.wide { width: 880px; }
.import-table input, .import-table select { width: 100%; padding: 5px 7px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; }
h4 { margin: 14px 0 6px; font-size: 14px; }
</style>
