# TEDSWS-524 ## PRD features not implemented in the MVP

Need to extend the backend api for the web curation app.


specs 

Curators can view and sort automatic Resolution Decisions results by:
• Confidence score
• Processing date
• Cluster size (THIS IS MISSING) 
Curators can perform the following actions:
• Accept or Reject Resolution Decisions
• Manually assign entities to alternative clusters (overriding automatic decisions)
• Search Resolution Decisions by text in the entity representation and any other 
entity metadata stored in the ERS data store 
• Filter Resolution Decisions by entity type, confidence range, and status 
(Pending/Reviewed) (THIS IS MISSING) 
• Apply bulk actions (Approve, Reject, Assign) .to multiple Resolution Decisions 
• Re-cluster and Remove-from-cluster actions will not support bulk 
operations.

TODO: 
add cluster size to statistics 
Add possibility to filter by status pending/reviewed

---


- Analyze how thes currently missing pecs are reflected in the curration API endpoints and data models, and design the necessary extensions to support these features.
- Propose solutions and write them down into  TEDSWS-524-solution-spec.md; 
- challeng the colutiona dpropose an improvment if needed.
