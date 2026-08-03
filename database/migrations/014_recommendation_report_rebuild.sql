-- 推荐报告不保留旧类型和历史产物。报告正文、消息、任务、Trace 与附件关联
-- 一次性清空，推荐会话和已选候选继续保留，可按新规则重新生成。
with recursive report_jobs as (
  select id
  from background_job
  where job_type = 'recommendation_report_generate'
     or entity_type = 'recommendation_report'
  union all
  select child.id
  from background_job child
  join report_jobs parent on child.parent_job_id = parent.id
)
delete from ai_trace
where job_id in (select id from report_jobs)
   or entity_type = 'recommendation_report'
   or node_name in (
     'recommendation_report_writer',
     'recommendation_target_report_writer',
     'recommendation_buyer_report_writer'
   );

with recursive report_jobs as (
  select id
  from background_job
  where job_type = 'recommendation_report_generate'
     or entity_type = 'recommendation_report'
  union all
  select child.id
  from background_job child
  join report_jobs parent on child.parent_job_id = parent.id
)
delete from background_job
where id in (select id from report_jobs);

update recommendation_selected_item
set selected_from_message_id = null
where selected_from_message_id in (
  select id
  from recommendation_message
  where metadata_json ->> 'message_type' = 'recommendation_report'
     or metadata_json ->> 'report_id' in (
       select id::text from recommendation_report
     )
);

delete from recommendation_message
where metadata_json ->> 'message_type' = 'recommendation_report'
   or metadata_json ->> 'report_id' in (
     select id::text from recommendation_report
   );

delete from attachment_link
where entity_type = 'recommendation_report';

update buyer_seller_relation
set created_from_report_id = null
where created_from_report_id is not null;

delete from recommendation_report;

update recommendation_session
set report_count = 0
where report_count <> 0;

alter table recommendation_report
  drop constraint if exists recommendation_report_report_type_check;

alter table recommendation_report
  add constraint recommendation_report_report_type_check
  check (report_type in (
    'buyer_facing_target_report',
    'seller_facing_buyer_report'
  ));
