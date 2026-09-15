/** 展示层格式化：英文枚举 → 中文标签。后端只传英文值，中文都在这一层。 */

const NATURE = {
  cold: '寒',
  cool: '凉',
  neutral: '平',
  warm: '温',
  hot: '热',
  unknown: '未知',
};

const FLAVOR = {
  sour: '酸',
  bitter: '苦',
  sweet: '甘',
  pungent: '辛',
  salty: '咸',
  bland: '淡',
  astringent: '涩',
};

const MEAL_TIME = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐',
  late_night: '夜宵',
  unknown: '未指明',
};

const COOKING = {
  raw: '生',
  boiled: '煮',
  steamed: '蒸',
  stir_fried: '炒',
  deep_fried: '油炸',
  grilled: '烤',
  cold: '冰镇',
  pickled: '腌制',
  unknown: '',
};

/** 体质选项。与后端 backend/data/constitution.json 保持一致 */
const CONSTITUTIONS = [
  { id: 'balanced', label: '平和质', one_line: '吃得好睡得着，寒热都不太敏感' },
  { id: 'qi_deficiency', label: '气虚质', one_line: '容易累、稍动就出汗、易感冒' },
  { id: 'yang_deficiency', label: '阳虚质', one_line: '怕冷、手脚凉、吃凉的容易不舒服' },
  { id: 'phlegm_damp', label: '痰湿质', one_line: '身体偏重、易困倦、舌苔厚腻' },
  { id: 'damp_heat', label: '湿热质', one_line: '容易长痘、口苦、面油' },
];

function natureLabel(v) {
  return NATURE[v] || '未知';
}

function flavorLabel(v) {
  return FLAVOR[v] || v;
}

function mealTimeLabel(v) {
  return MEAL_TIME[v] || '未指明';
}

function cookingLabel(v) {
  return COOKING[v] || '';
}

/** 属性来源 → 中文说明。用于"待验证"标记的提示文案 */
const SOURCE_LABELS = {
  rule: '查表',
  composed: '按烹饪方式推算',
  llm: '模型推测',
  unresolved: '无法判定',
};

/** 低于此置信度时界面不显示寒热属性 */
const CONF_SHOW_THRESHOLD = 0.3;

function sourceLabel(v) {
  return SOURCE_LABELS[v] || '';
}

/**
 * 整理单个食物的验证信息。
 * 三层架构要求：非硬规则库的结果必须标注；
 * 置信度低于阈值时**不显示**寒热属性（但数据仍在，Agent2 能看到）。
 */
function decorateVerification(f) {
  const v = f.verification || {};
  const confidence = typeof v.confidence === 'number' ? v.confidence : 0.3;
  const source = v.source || 'llm';
  const unverified = v.unverified !== false;
  const showNature = confidence >= CONF_SHOW_THRESHOLD;
  return {
    source,
    sourceText: sourceLabel(source),
    confidence,
    confidencePct: Math.round(confidence * 100),
    unverified,
    showNature,
    detail: v.detail || '',
  };
}

/** 把解析结果整理成页面直接可渲染的结构 */
function decorateParsed(parsed) {
  if (!parsed) {
    return {
      foods: [],
      chips: [],
      mealTimeText: '未指明',
      overallText: '未知',
      confidencePct: 0,
      unverifiedCount: 0,
      maxSourceText: '',
    };
  }
  const foods = (parsed.foods || []).map((f) => {
    const flavors = (f.flavors || []).map(flavorLabel).join('');
    const cooking = cookingLabel(f.cooking);
    const ver = decorateVerification(f);
    // 置信度太低时不把属性写进标签文字，前端就不显示了
    const naturePart = ver.showNature ? natureLabel(f.nature) : '';
    const natureText = ver.showNature ? natureLabel(f.nature) : '未判定';
    return {
      name: f.name,
      natureKey: ver.showNature ? f.nature || 'unknown' : 'unknown',
      natureText,
      flavorText: flavors,
      cookingText: cooking,
      amount: f.amount_desc || '',
      note: f.note || '',
      // 标签文字：麻辣烫 · 热 · 辛咸（低于阈值时省略属性段）
      tagText: [f.name, naturePart, flavors].filter(Boolean).join(' · '),
      verification: ver,
    };
  });

  const unverifiedCount = foods.filter((f) => f.verification.unverified).length;

  return {
    foods,
    mealTimeText: mealTimeLabel(parsed.meal_time),
    overallKey: parsed.overall_nature || 'unknown',
    overallText: natureLabel(parsed.overall_nature),
    confidencePct: Math.round((parsed.confidence || 0) * 100),
    summary: parsed.summary || '',
    uncertain: parsed.uncertain_items || [],
    unverifiedCount,
    // 只要存在未验证项，就在结果页给一行总说明
    hasUnverified: unverifiedCount > 0,
  };
}

/** 把推荐结果整理成页面可渲染结构 */
function decorateRecommendations(recs) {
  return (recs || []).map((r) => {
    const brew = r.brew || {};
    return {
      title: r.title,
      scorePct: Math.round((r.score || 0) * 100),
      herbs: (r.herbs || []).map((h) => ({
        name: h.name,
        amount: h.amount_g,
        role: h.role || '',
        natureText: natureLabel(h.nature),
        meridians: (h.meridians || []).join('/'),
      })),
      brewLine: [
        brew.vessel || '保温杯',
        (brew.water_ml || 400) + 'ml',
        (brew.water_temp_c || 95) + '℃',
        '焖' + (brew.steep_min || 8) + '分钟',
        '可续水' + (brew.refill_times || 1) + '次',
      ].join(' · '),
      steps: brew.steps || [],
      fitReason: r.fit_reason || '',
      cautions: r.cautions || [],
    };
  });
}

/** 体质 key → 显示名 */
function constitutionLabel(id) {
  const found = CONSTITUTIONS.filter((c) => c.id === id)[0];
  return found ? found.label : id;
}

module.exports = {
  NATURE,
  FLAVOR,
  MEAL_TIME,
  CONSTITUTIONS,
  SOURCE_LABELS,
  CONF_SHOW_THRESHOLD,
  natureLabel,
  flavorLabel,
  mealTimeLabel,
  cookingLabel,
  sourceLabel,
  decorateVerification,
  decorateParsed,
  decorateRecommendations,
  constitutionLabel,
};
