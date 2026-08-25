export function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return <><section className="page-heading"><div><span className="eyebrow">MIGRATION QUEUE</span><h1>{title}</h1><p>{description}</p></div></section><section className="panel placeholder-panel"><div className="placeholder-mark">✦</div><h2>页面组件迁移待办</h2><p>应用壳、路由和设计系统已经可用。该模块将在对应后端契约确定后接入 Mock API。</p></section></>
}
