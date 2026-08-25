-- 买家主体解析与调研链路的唯一 schema 改动：放开 research_proposal 的实体白名单。
--
-- 解析与调研的提案都落 research_proposal，用 source_type 区分 material / web，
-- 不新增 buyer_party_update 这个 action_type。三条理由：
--   形状匹配 —— extracted_action 是为「一段业务更新拆成多种动作」设计的，
--   买家主体解析只产出字段事实一种东西，和调研输出同形
--   字段更全 —— conflict_kind 四态、as_of_date / period_label / source_url /
--   source_excerpt / confidence 正好是财务快照与冲突调和需要的
--   省掉一次三处同步 —— 不用改 ALLOWED_ACTION_TYPES + DB CHECK + apply 分支
--
-- proposal_kind 仍只用 structured_fact：买家主体不设画像栏，
-- 两个业务字段 business_tags_json + business_summary 就是全部。
--
-- 注意：本文件的注释里不能出现分号。自制 splitter 按分号切语句，
-- 注释里的分号会切坏语句、部署直接挂（有过事故，见 AGENTS.md）。

alter table research_proposal
  drop constraint if exists research_proposal_entity_type_check;

alter table research_proposal
  add constraint research_proposal_entity_type_check
  check (entity_type in ('seller_target', 'buyer_intent', 'buyer_party'));
