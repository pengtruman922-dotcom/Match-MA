-- 0728: give "查到了但一条都没落库" its own research outcome.
--
-- 这一轮排查的起点就是这个缺口：2026-07-22 两次调研写出了完整画像，却因为
-- prompt 的来源字段和代码收货口对不上被全额丢弃，结论记成 no_public_information
-- —— 于是「公开渠道确实没有」和「查到了但系统没接住」在库里长得一模一样，
-- 界面上也就完全静默。found_but_rejected 把这两件事分开。
--
-- 只重建 check 约束，不动数据：历史行里的三个取值仍然合法。

alter table seller_target
  drop constraint if exists chk_seller_target_research_outcome;

alter table seller_target
  add constraint chk_seller_target_research_outcome
  check (
    research_last_outcome is null
    or research_last_outcome = any (
      array['found'::text, 'found_but_rejected'::text, 'no_public_information'::text, 'failed'::text]
    )
  );
