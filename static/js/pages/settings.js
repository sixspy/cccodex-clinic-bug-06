import { api, escapeHtml } from '../api.js';

export async function renderSettings(el) {
  const data = await api('/api/settings');
  const items = data.items || [];
  const snapshot = data.snapshot || {};

  el.innerHTML = `
    <div class="card">
      <h2>台参数</h2>
      <p class="muted">控制质控自动扫描开关、补采最大次数、配额告警与对账口径标签等。修改会写审计。</p>
      <div class="grid">
        <div class="stat"><div class="n">${snapshot.backfill_max_attempt || '-'}</div><div class="l">补采最大次数</div></div>
        <div class="stat"><div class="n">${snapshot.qc_auto_scan || '-'}</div><div class="l">自动质控</div></div>
        <div class="stat"><div class="n">${snapshot.site_quota_warn || '-'}</div><div class="l">配额告警阈值</div></div>
        <div class="stat"><div class="n">${escapeHtml((snapshot.clinic_timezone || '-').slice(0, 12))}</div><div class="l">时区</div></div>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>键</th><th>说明</th><th>当前值</th><th>新值</th><th>操作</th></tr></thead>
        <tbody>
          ${items.map((s) => `
            <tr>
              <td><code>${escapeHtml(s.key)}</code></td>
              <td>${escapeHtml(s.label)}</td>
              <td><strong>${escapeHtml(s.value)}</strong></td>
              <td><input data-key="${escapeHtml(s.key)}" value="${escapeHtml(s.value)}" /></td>
              <td><button data-save="${escapeHtml(s.key)}">保存</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div id="msg" class="muted" style="margin-top:10px"></div>
    </div>
    <div class="card">
      <h2>预留切口（后续题面）</h2>
      <ul class="muted">
        <li>访视行跨中心去重策略与冲突裁决面板</li>
        <li>方案换版后存量批次字段兼容扫描</li>
        <li>补采任务分片与并发上限</li>
        <li>对账报告导出与差异工单</li>
      </ul>
      <div class="detail-box">${escapeHtml(JSON.stringify(snapshot, null, 2))}</div>
    </div>`;

  const msg = el.querySelector('#msg');
  el.querySelectorAll('[data-save]').forEach((btn) => {
    btn.onclick = async () => {
      const key = btn.dataset.save;
      const input = el.querySelector(`input[data-key="${key}"]`);
      try {
        const updated = await api('/api/settings/update', {
          method: 'POST',
          body: JSON.stringify({ key, value: input.value }),
        });
        msg.className = 'muted';
        msg.textContent = `已保存 ${updated.key} = ${updated.value}`;
        await renderSettings(el);
      } catch (e) {
        msg.className = 'err';
        msg.textContent = e.message;
      }
    };
  });

  try {
    const dash = await api('/api/rule_pack/dash');
    const chipCls = dash.aligned ? 'ok' : 'bad';
    el.insertAdjacentHTML('beforeend', `<div class="card" style="margin-top:1rem">
      <h3>规则包钉定 <span class="chip ${chipCls}" data-thick="rule_pack">${escapeHtml(dash.chip)}</span></h3>
      <div class="grid">
        <div class="stat"><div class="n">${escapeHtml(dash.version || '无')}</div><div class="l">包版本号</div></div>
        <div class="stat"><div class="n">${dash.pack_count}</div><div class="l">落点行</div></div>
        <div class="stat"><div class="n">${dash.aligned ? '对齐' : '未对齐'}</div><div class="l">读轨口径</div></div>
      </div>
      <p class="muted">读轨 ${escapeHtml(dash.active_read)} · 切流指纹 ${escapeHtml(dash.cutover_fp || '空')} · 拒回刷 ${dash.reject_refresh} · 真值 ${escapeHtml(dash.truth)} · 徽标拧花 ${dash.panel_pack_mismatch}</p>
      <div class="row">
        <button id="go_rule_pack" type="button">落台提交</button>
        <button id="cut_rule_pack" type="button">切流账册钉定</button>
      </div>
      <div id="rpMsg" class="muted" style="margin-top:8px"></div>
    </div>`);
    const rpMsg = el.querySelector('#rpMsg');
    const go = el.querySelector('#go_rule_pack');
    if (go) go.onclick = async () => {
      try {
        const r = await api('/api/rule_pack/commit', { method: 'POST', body: JSON.stringify({ note: '台参数落台' }) });
        rpMsg.className = 'muted';
        rpMsg.textContent = r.message || '已落台';
        await renderSettings(el);
      } catch (e) {
        rpMsg.className = 'err';
        rpMsg.textContent = e.message;
      }
    };
    const cut = el.querySelector('#cut_rule_pack');
    if (cut) cut.onclick = async () => {
      try {
        const r = await api('/api/rule_pack/cutover', { method: 'POST', body: JSON.stringify({ ref_id: 1, note: '规则包钉定入账' }) });
        rpMsg.className = 'muted';
        rpMsg.textContent = `账册已钉 ${r.version} 指纹 ${r.cutover_fp}`;
        await renderSettings(el);
      } catch (e) {
        rpMsg.className = 'err';
        rpMsg.textContent = e.message;
      }
    };
  } catch (e) { /* optional surface */ }

}
