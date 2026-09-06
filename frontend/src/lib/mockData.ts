import type {
  Explanation,
  Lang,
  SceneId,
  SubjectId,
  Submission,
  Transaction,
  UiLang,
} from './types'

export const SUBJECTS: SubjectId[] = [
  'math',
  'geometry',
  'physics',
  'chemistry',
  'biology',
  'informatics',
]

export const GRADES = [5, 6, 7, 8, 9, 10, 11]

/** Price list, in tenge. Shown to the user verbatim on the Billing page. */
export const PRICES = {
  explanation: 120,
  assessment: 400,
  grading: 60,
}

const DAY = 24 * 60 * 60 * 1000
const ANCHOR = new Date('2026-09-04T10:00:00Z').getTime()

/** Deterministic date helper so mock data never drifts between renders. */
function daysAgo(days: number, hour = 10): string {
  const d = new Date(ANCHOR - days * DAY)
  d.setHours(hour, (days * 7) % 60, 0, 0)
  return d.toISOString()
}

interface Seed {
  question: string
  subject: SubjectId
  lang: Lang
  scene: SceneId
  duration: number
  blocks: Explanation['blocks']
}

export const EXPLANATION_SEEDS: Record<SceneId, Seed> = {
  pythagoras: {
    question: 'Пифагор теоремасы қалай дәлелденеді?',
    subject: 'geometry',
    lang: 'kk',
    scene: 'pythagoras',
    duration: 42,
    blocks: [
      {
        kind: 'paragraph',
        text: 'Тік бұрышты үшбұрышта гипотенузаға қарсы жатқан бұрыш 90° болады. Теорема осы үшбұрыштың үш қабырғасының арасындағы байланысты береді.',
      },
      {
        kind: 'step',
        title: '1. Шаршы саламыз',
        text: 'Қабырғасы a + b болатын шаршы аламыз. Оның ауданы (a + b)².',
      },
      {
        kind: 'step',
        title: '2. Төрт үшбұрышты орналастырамыз',
        text: 'Катеттері a мен b болатын төрт бірдей үшбұрышты шаршының ішіне екі түрлі тәсілмен қоямыз.',
      },
      {
        kind: 'step',
        title: '3. Бос ауданды салыстырамыз',
        text: 'Бірінші орналасуда бос аудан a² + b², екіншісінде c² болады. Алынған үшбұрыштардың ауданы бірдей болғандықтан, бос аудандар да тең.',
      },
      { kind: 'formula', text: 'a² + b² = c²' },
      {
        kind: 'paragraph',
        text: 'Демек гипотенузаның ұзындығы c = √(a² + b²). Кері тұжырым да дұрыс: қабырғалары осы теңдікті қанағаттандыратын үшбұрыш тік бұрышты болады.',
      },
    ],
  },
  quadratic: {
    question: 'Квадраттық функцияның графигі неге парабола болады?',
    subject: 'math',
    lang: 'kk',
    scene: 'quadratic',
    duration: 38,
    blocks: [
      {
        kind: 'paragraph',
        text: 'y = ax² + bx + c функциясының графигі әрқашан парабола. Себебін толық квадратқа келтіру арқылы көруге болады.',
      },
      { kind: 'formula', text: 'y = a(x + b/2a)² + (c − b²/4a)' },
      {
        kind: 'step',
        title: '1. Негізгі парабола',
        text: 'y = x² графигі — нөлден екі жаққа симметриялы қисық. Әр x үшін y мәні x-тің квадратына тең.',
      },
      {
        kind: 'step',
        title: '2. Жылжыту мен созу',
        text: 'a коэффициенті параболаны тік бағытта созады немесе қысады, b мен c оны жазықтықта жылжытады. Пішіні өзгермейді.',
      },
      {
        kind: 'paragraph',
        text: 'Сондықтан кез келген квадраттық функцияның графигі — орны мен енін ғана өзгерткен сол бір парабола.',
      },
    ],
  },
  circleArea: {
    question: 'Дөңгелектің ауданы неге πr² болады?',
    subject: 'geometry',
    lang: 'kk',
    scene: 'circleArea',
    duration: 35,
    blocks: [
      {
        kind: 'paragraph',
        text: 'Дөңгелекті жұқа сақиналарға немесе секторларға бөліп, оларды қайта құрастыру арқылы формуланы шығаруға болады.',
      },
      {
        kind: 'step',
        title: '1. Секторларға бөлеміз',
        text: 'Дөңгелекті бірдей секторларға бөлеміз. Секторлар неғұрлым көп болса, олар соғұрлым жіңішке үшбұрышқа ұқсайды.',
      },
      {
        kind: 'step',
        title: '2. Тіктөртбұрышқа жинаймыз',
        text: 'Секторларды кезектестіріп қатарға тізсек, ені r, ұзындығы шеңбер ұзындығының жартысына тең фигура шығады.',
      },
      { kind: 'formula', text: 'S = r · (2πr / 2) = πr²' },
      {
        kind: 'paragraph',
        text: 'Секторлар саны шексіз өскенде фигура нақты тіктөртбұрышқа айналады, ал ауданы πr² болып қалады.',
      },
    ],
  },
  photosynthesis: {
    question: 'Фотосинтез қалай жүреді?',
    subject: 'biology',
    lang: 'kk',
    scene: 'photosynthesis',
    duration: 46,
    blocks: [
      {
        kind: 'paragraph',
        text: 'Фотосинтез — жасыл өсімдіктің жарық энергиясын химиялық энергияға айналдыру процесі. Ол жапырақ жасушасындағы хлоропластта жүреді.',
      },
      {
        kind: 'step',
        title: '1. Жарық фазасы',
        text: 'Хлорофилл жарықты сіңіреді. Су молекуласы ыдырап, оттегі бөлінеді, ал энергия уақытша тасымалдаушыларға жиналады.',
      },
      {
        kind: 'step',
        title: '2. Қараңғы фаза',
        text: 'Жиналған энергия көмірқышқыл газын глюкозаға айналдыруға жұмсалады. Бұл фазаға жарық тікелей қажет емес.',
      },
      { kind: 'formula', text: '6CO₂ + 6H₂O + жарық → C₆H₁₂O₆ + 6O₂' },
      {
        kind: 'paragraph',
        text: 'Нәтижесінде өсімдік қоректенеді, ал атмосфераға оттегі бөлінеді.',
      },
    ],
  },
  newton: {
    question: 'Ньютонның екінші заңы нені білдіреді?',
    subject: 'physics',
    lang: 'kk',
    scene: 'newton',
    duration: 33,
    blocks: [
      {
        kind: 'paragraph',
        text: 'Екінші заң денеге әсер ететін күш пен оның үдеуі арасындағы байланысты береді.',
      },
      { kind: 'formula', text: 'F = m · a' },
      {
        kind: 'step',
        title: 'Күш екі есе өссе',
        text: 'Масса өзгермесе, күшті екі есе арттырғанда үдеу де екі есе артады.',
      },
      {
        kind: 'step',
        title: 'Масса екі есе өссе',
        text: 'Күш өзгермесе, массасы екі есе ауыр дене екі есе баяу үдейді.',
      },
      {
        kind: 'paragraph',
        text: 'Сондықтан бірдей күшпен итерілген жеңіл арба ауыр арбадан жылдам қозғалады.',
      },
    ],
  },
  derivative: {
    question: 'Что такое производная функции?',
    subject: 'math',
    lang: 'ru',
    scene: 'derivative',
    duration: 40,
    blocks: [
      {
        kind: 'paragraph',
        text: 'Производная показывает, насколько быстро меняется функция в конкретной точке. Геометрически это наклон касательной к графику.',
      },
      {
        kind: 'step',
        title: '1. Секущая',
        text: 'Возьмём две точки на графике и проведём через них прямую. Её наклон — средняя скорость изменения на этом участке.',
      },
      {
        kind: 'step',
        title: '2. Сближаем точки',
        text: 'Приближаем вторую точку к первой. Секущая поворачивается и в пределе становится касательной.',
      },
      { kind: 'formula', text: "f'(x) = lim (h→0) [f(x + h) − f(x)] / h" },
      {
        kind: 'paragraph',
        text: 'Наклон этой касательной и есть производная в точке x. Если он положительный — функция растёт, если отрицательный — убывает.',
      },
    ],
  },
  reaction: {
    question: 'Химиялық реакция теңдеуін қалай теңестіреміз?',
    subject: 'chemistry',
    lang: 'kk',
    scene: 'reaction',
    duration: 36,
    blocks: [
      {
        kind: 'paragraph',
        text: 'Теңестіру — реакцияға дейін және кейін әр элементтің атом санын теңестіру. Масса сақталу заңы осыны талап етеді.',
      },
      {
        kind: 'step',
        title: '1. Атомдарды санаймыз',
        text: 'Сол жақтағы және оң жақтағы әр элементтің атомдарын бөлек санаймыз.',
      },
      {
        kind: 'step',
        title: '2. Коэффициент қоямыз',
        text: 'Формуладағы индекстерді өзгертпей, тек алдындағы коэффициенттерді таңдаймыз.',
      },
      { kind: 'formula', text: '2H₂ + O₂ → 2H₂O' },
      {
        kind: 'paragraph',
        text: 'Енді екі жағында да 4 сутек және 2 оттек атомы бар — теңдеу теңестірілді.',
      },
    ],
  },
}

let seq = 0
function makeExplanation(scene: SceneId, days: number, saved = true): Explanation {
  const seed = EXPLANATION_SEEDS[scene]
  seq += 1
  return {
    id: `exp-${scene}-${seq}`,
    question: seed.question,
    subject: seed.subject,
    lang: seed.lang,
    createdAt: daysAgo(days),
    scene: seed.scene,
    duration: seed.duration,
    blocks: seed.blocks,
    status: 'complete',
    saved,
  }
}

/** Extra saved items so the Library grid looks lived-in. */
const EXTRA: Array<{ scene: SceneId; question: string; days: number; lang?: Lang }> = [
  {
    scene: 'newton',
    question: 'Неге ауыр және жеңіл дене бірдей уақытта құлайды?',
    days: 6,
  },
  { scene: 'quadratic', question: 'Дискриминант нені көрсетеді?', days: 8 },
  { scene: 'photosynthesis', question: 'Жапырақ неге жасыл түсті?', days: 11 },
  {
    scene: 'circleArea',
    question: 'Как связаны длина окружности и её радиус?',
    days: 13,
    lang: 'ru',
  },
  { scene: 'reaction', question: 'Тотығу реакциясы деген не?', days: 16 },
]

export function buildLibrary(): Explanation[] {
  const base = [
    makeExplanation('pythagoras', 0),
    makeExplanation('derivative', 1),
    makeExplanation('photosynthesis', 2),
    makeExplanation('newton', 3),
    makeExplanation('quadratic', 4),
    makeExplanation('circleArea', 5),
    makeExplanation('reaction', 7),
  ]
  const extra = EXTRA.map((item, index) => {
    const made = makeExplanation(item.scene, item.days)
    return {
      ...made,
      id: `exp-extra-${index}`,
      question: item.question,
      lang: item.lang ?? made.lang,
    }
  })
  return [...base, ...extra]
}

export const EXAMPLE_QUESTIONS: Record<Lang, string[]> = {
  kk: [
    'Пифагор теоремасы қалай дәлелденеді?',
    'Дөңгелектің ауданы неге πr² болады?',
    'Ньютонның екінші заңы нені білдіреді?',
  ],
  ru: [
    'Что такое производная функции?',
    'Почему график квадратичной функции — парабола?',
    'Как уравнять химическое уравнение?',
  ],
}

/** Landing page example cards. */
export const LANDING_EXAMPLES: Array<{ scene: SceneId; subject: SubjectId }> = [
  { scene: 'circleArea', subject: 'geometry' },
  { scene: 'newton', subject: 'physics' },
  { scene: 'photosynthesis', subject: 'biology' },
]

export const TEAM = [
  {
    name: 'Әбілмансұр Иса',
    initials: 'ӘИ',
    title: 'CEO',
    roleKk: 'Өнім мен даму бағыты. Мектептермен серіктестік.',
    roleRu: 'Продукт и направление развития. Партнёрство со школами.',
    roleEn: 'Product and direction. School partnerships.',
  },
  {
    name: 'Марат Серіков',
    initials: 'МС',
    title: 'CTO',
    roleKk: 'Инженерия. Генерация мен рендер конвейері.',
    roleRu: 'Инженерия. Конвейер генерации и рендера.',
    roleEn: 'Engineering. The generation and rendering pipeline.',
  },
]

/** Where to reach the team. Shown on the landing page and in the footer. */
export const CONTACT = {
  phone: '+7 707 910 5255',
  phoneHref: 'tel:+77079105255',
  email: 'gidraisa77@gmail.com',
  emailHref: 'mailto:gidraisa77@gmail.com',
}

/** Question templates used by the Generate page, keyed by subject. */
export const QUESTION_TEMPLATES: Record<SubjectId, Record<Lang, string[]>> = {
  math: {
    kk: [
      '«{topic}» тақырыбы бойынша теңдеуді шешіңіз және шешім барысын жазыңыз.',
      '«{topic}» тақырыбындағы өрнекті ықшамдаңыз.',
      'Берілген функцияның графигін салыңыз және «{topic}» бойынша қасиеттерін атаңыз.',
      '«{topic}» тақырыбына есеп құрастырып, оны шешіңіз.',
      'Мәтінді есепті теңдеуге айналдырып, «{topic}» әдісімен шешіңіз.',
      '«{topic}» бойынша тұжырымның дұрыстығын мысалмен негіздеңіз.',
      'Қателікті табыңыз: берілген шешімде «{topic}» ережесі қате қолданылған.',
      '«{topic}» тақырыбы бойынша екі әдісті салыстырыңыз.',
    ],
    ru: [
      'Решите уравнение по теме «{topic}» и запишите ход решения.',
      'Упростите выражение по теме «{topic}».',
      'Постройте график функции и назовите её свойства по теме «{topic}».',
      'Составьте задачу по теме «{topic}» и решите её.',
      'Переведите текстовую задачу в уравнение и решите методом «{topic}».',
      'Обоснуйте утверждение по теме «{topic}» на примере.',
      'Найдите ошибку: в приведённом решении неверно применено правило «{topic}».',
      'Сравните два способа решения по теме «{topic}».',
    ],
  },
  geometry: {
    kk: [
      '«{topic}» бойынша фигураның ауданын табыңыз.',
      'Сызбаны салып, «{topic}» тақырыбындағы белгісіз бұрышты табыңыз.',
      '«{topic}» теоремасын тұжырымдап, дәлелдеңіз.',
      'Ұқсас фигуралардың қатынасын «{topic}» арқылы негіздеңіз.',
      '«{topic}» бойынша дене көлемін есептеңіз.',
      'Берілген шарт бойынша «{topic}» тақырыбына сызба салыңыз.',
      '«{topic}» бойынша тұжырым дұрыс па? Жауабыңызды негіздеңіз.',
      'Практикалық жағдайды «{topic}» көмегімен шешіңіз.',
    ],
    ru: [
      'Найдите площадь фигуры по теме «{topic}».',
      'Постройте чертёж и найдите неизвестный угол по теме «{topic}».',
      'Сформулируйте и докажите теорему по теме «{topic}».',
      'Обоснуйте отношение подобных фигур через «{topic}».',
      'Вычислите объём тела по теме «{topic}».',
      'Постройте чертёж по условию к теме «{topic}».',
      'Верно ли утверждение по теме «{topic}»? Обоснуйте.',
      'Решите практическую задачу с помощью «{topic}».',
    ],
  },
  physics: {
    kk: [
      '«{topic}» бойынша есептің шартын жазып, шешіңіз.',
      'Тәжірибе нәтижесін «{topic}» заңымен түсіндіріңіз.',
      '«{topic}» тақырыбындағы шаманың өлшем бірлігін атап, формуласын жазыңыз.',
      'Графикті талдап, «{topic}» бойынша қорытынды жасаңыз.',
      '«{topic}» құбылысына күнделікті өмірден мысал келтіріңіз.',
      'Күштер сызбасын салып, «{topic}» бойынша тепе-теңдікті тексеріңіз.',
      'Есепте қате жіберілген: «{topic}» бойынша дұрыс шешімді жазыңыз.',
      '«{topic}» бойынша екі жағдайды салыстырыңыз.',
    ],
    ru: [
      'Запишите условие и решите задачу по теме «{topic}».',
      'Объясните результат опыта законом «{topic}».',
      'Назовите единицу измерения и запишите формулу по теме «{topic}».',
      'Проанализируйте график и сделайте вывод по теме «{topic}».',
      'Приведите бытовой пример явления «{topic}».',
      'Постройте схему сил и проверьте равновесие по теме «{topic}».',
      'В решении допущена ошибка: запишите верное решение по теме «{topic}».',
      'Сравните два случая по теме «{topic}».',
    ],
  },
  chemistry: {
    kk: [
      '«{topic}» бойынша реакция теңдеуін теңестіріңіз.',
      'Заттың массасын «{topic}» бойынша есептеңіз.',
      '«{topic}» тақырыбындағы қосылыстың атауын жазыңыз.',
      'Реакция түрін анықтап, «{topic}» бойынша негіздеңіз.',
      '«{topic}» бойынша тәжірибе барысын сипаттаңыз.',
      'Ерітіндінің концентрациясын «{topic}» әдісімен табыңыз.',
      '«{topic}» бойынша қауіпсіздік ережесін атаңыз.',
      'Кестені толтырып, «{topic}» бойынша заңдылықты жазыңыз.',
    ],
    ru: [
      'Уравняйте реакцию по теме «{topic}».',
      'Вычислите массу вещества по теме «{topic}».',
      'Запишите название соединения по теме «{topic}».',
      'Определите тип реакции и обоснуйте через «{topic}».',
      'Опишите ход опыта по теме «{topic}».',
      'Найдите концентрацию раствора методом «{topic}».',
      'Назовите правило безопасности по теме «{topic}».',
      'Заполните таблицу и сформулируйте закономерность по теме «{topic}».',
    ],
  },
  biology: {
    kk: [
      '«{topic}» процесінің кезеңдерін ретімен жазыңыз.',
      'Сызбада «{topic}» бөліктерін белгілеңіз.',
      '«{topic}» бойынша екі организмді салыстырыңыз.',
      'Тәжірибе нәтижесін «{topic}» арқылы түсіндіріңіз.',
      '«{topic}» тақырыбындағы терминге анықтама беріңіз.',
      'Себеп-салдар байланысын «{topic}» бойынша көрсетіңіз.',
      '«{topic}» бұзылғанда не болатынын сипаттаңыз.',
      '«{topic}» бойынша кестені толтырыңыз.',
    ],
    ru: [
      'Запишите этапы процесса «{topic}» по порядку.',
      'Обозначьте на схеме части «{topic}».',
      'Сравните два организма по теме «{topic}».',
      'Объясните результат опыта через «{topic}».',
      'Дайте определение термину по теме «{topic}».',
      'Покажите причинно-следственную связь по теме «{topic}».',
      'Опишите, что произойдёт при нарушении «{topic}».',
      'Заполните таблицу по теме «{topic}».',
    ],
  },
  informatics: {
    kk: [
      '«{topic}» алгоритмінің қадамдарын жазыңыз.',
      'Берілген кодтың нәтижесін «{topic}» бойынша болжаңыз.',
      '«{topic}» бойынша блок-схема сызыңыз.',
      'Кодтағы қатені тауып, «{topic}» бойынша түзетіңіз.',
      '«{topic}» әдісінің тиімділігін бағалаңыз.',
      'Есепті «{topic}» көмегімен шешетін бағдарлама жазыңыз.',
      '«{topic}» бойынша деректер құрылымын таңдап, негіздеңіз.',
      'Екі шешімді «{topic}» бойынша салыстырыңыз.',
    ],
    ru: [
      'Запишите шаги алгоритма «{topic}».',
      'Предскажите результат кода по теме «{topic}».',
      'Начертите блок-схему по теме «{topic}».',
      'Найдите ошибку в коде и исправьте её по теме «{topic}».',
      'Оцените эффективность метода «{topic}».',
      'Напишите программу, решающую задачу через «{topic}».',
      'Выберите структуру данных по теме «{topic}» и обоснуйте выбор.',
      'Сравните два решения по теме «{topic}».',
    ],
  },
}

const NOTES: Record<UiLang, string[]> = {
  en: [
    'Fully correct solution.',
    'Correct answer, but no working shown.',
    'Right formula, arithmetic slip in the calculation.',
    'No unit given.',
    'The last step was left unfinished.',
    'Only the answer is written, with no explanation.',
  ],
  kk: [
    'Толық дұрыс шешім.',
    'Жауап дұрыс, бірақ шешім барысы жазылмаған.',
    'Формула дұрыс таңдалған, есептеуде арифметикалық қате.',
    'Өлшем бірлігі көрсетілмеген.',
    'Соңғы қадам аяқталмай қалған.',
    'Түсінік берілмеген, тек жауап жазылған.',
  ],
  ru: [
    'Решение полностью верное.',
    'Ответ верный, но ход решения не записан.',
    'Формула выбрана верно, ошибка в вычислении.',
    'Не указана единица измерения.',
    'Последний шаг не завершён.',
    'Пояснение отсутствует, записан только ответ.',
  ],
}

const STUDENT_NAMES = [
  'Айсұлу Қайрат',
  'Дінмұхаммед Оспан',
  'Мадина Серікова',
  'Ерасыл Тұрсын',
  'Алишер Жақсылық',
  'Камила Нұрлан',
]

export function buildSubmissions(lang: UiLang): Submission[] {
  const notes = NOTES[lang]
  return STUDENT_NAMES.map((student, index) => {
    const max = 20
    const breakdown = Array.from({ length: 5 }, (_, q) => {
      const perMax = 4
      const awarded = [4, 3, 4, 2, 4, 1][(index + q) % 6]
      return {
        number: q + 1,
        awarded: Math.min(awarded, perMax),
        max: perMax,
        note: notes[(index + q) % notes.length],
      }
    })
    const score = breakdown.reduce((sum, q) => sum + q.awarded, 0)
    return {
      id: `sub-${index + 1}`,
      student,
      fileName: `${student.split(' ')[0].toLowerCase()}-sor3.pdf`,
      score,
      max,
      gradedAt: daysAgo(index === 0 ? 0 : 1, 12 + index),
      status: 'graded' as const,
      breakdown,
    }
  })
}

export function buildTransactions(): Transaction[] {
  const rows: Array<[number, Transaction['action'], number, number]> = [
    [0, 'explanation', 4, -480],
    [0, 'grading', 6, -360],
    [1, 'assessment', 1, -400],
    [2, 'explanation', 7, -840],
    [3, 'topup', 1, 20000],
    [4, 'grading', 12, -720],
    [5, 'assessment', 2, -800],
    [6, 'explanation', 3, -360],
    [9, 'grading', 24, -1440],
    [12, 'assessment', 1, -400],
    [15, 'explanation', 9, -1080],
    [20, 'topup', 1, 15000],
  ]
  const detail: Record<Transaction['action'], string> = {
    explanation: '9 «А» сынып',
    assessment: 'Математика · 8 сынып',
    grading: 'СОР №3',
    topup: 'Kaspi',
  }
  return rows.map(([days, action, quantity, amount], index) => ({
    id: `tx-${index + 1}`,
    date: daysAgo(days, 9 + (index % 8)),
    action,
    detail: detail[action],
    quantity,
    amount,
  }))
}

/** Daily spend for the usage chart, per period. */
export const USAGE_SERIES: Record<'month' | 'quarter' | 'year', number[]> = {
  month: [0, 120, 360, 240, 0, 0, 480, 720, 400, 240, 120, 0, 0, 600, 840, 360],
  quarter: [3200, 4100, 2600, 5200, 4800, 3900, 6100, 5400, 4200, 3100, 5900, 4600],
  year: [12000, 9800, 14200, 11500, 16800, 13200, 4200, 5100, 15400],
}

export const USAGE_BREAKDOWN = {
  explanations: 23,
  assessments: 4,
  gradings: 42,
}
