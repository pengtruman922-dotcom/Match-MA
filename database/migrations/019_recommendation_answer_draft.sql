-- Writer 正文草稿：让「谁在写正文」和「浏览器还连着吗」彻底解耦。
--
-- 在此之前，正文是前端调 /answer-stream 时在 API 进程里生成的，落库动作排在
-- 流循环之后。客户端一断开，生成器就停在某次 yield 上，persist() 永远不执行 ——
-- 整段已经付费生成的正文直接丢失，会话停在「有 brief 无 answer」的黄点，
-- 重开会话又会重新生成、重新付费一次。
--
-- 修完之后 Writer 跟着 agent job 跑在 worker 里，边写边把当前全文节流写进这张
-- 表；/answer-stream 退化成订阅这张表的读者。所以这张表是**进行中的中间态**，
-- 不是历史资料：
--   * 正文写完 → 落 recommendation_message(agent_answer) 并删掉这里的草稿
--   * 用户中止 → 删掉草稿，不留半截
-- 因此它可以随时被清空而不损失任何东西，真相永远在 recommendation_message 里。
-- 施工单见《推荐问题修复第一批_正文可靠性与worker韧性0818.md》。

create table if not exists recommendation_answer_draft (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  session_id uuid not null,
  turn_id text not null,
  markdown text not null default ''::text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint recommendation_answer_draft_pkey primary key (id)
);

-- 一轮只有一份草稿。worker 侧的 upsert 直接挂在这个唯一约束上，
-- 双 worker 抢同一轮时后写的覆盖前写的，而不是长出两行谁也说不清的草稿。
create unique index if not exists uq_recommendation_answer_draft_turn
  on recommendation_answer_draft (session_id, turn_id);

alter table recommendation_answer_draft
  drop constraint if exists recommendation_answer_draft_session_id_fkey;
alter table recommendation_answer_draft
  add constraint recommendation_answer_draft_session_id_fkey
  foreign key (session_id) references recommendation_session(id) on delete cascade;

alter table recommendation_answer_draft
  drop constraint if exists recommendation_answer_draft_team_id_fkey;
alter table recommendation_answer_draft
  add constraint recommendation_answer_draft_team_id_fkey
  foreign key (team_id) references team(id);

alter table recommendation_answer_draft
  drop constraint if exists recommendation_answer_draft_workspace_id_fkey;
alter table recommendation_answer_draft
  add constraint recommendation_answer_draft_workspace_id_fkey
  foreign key (workspace_id) references workspace(id);
