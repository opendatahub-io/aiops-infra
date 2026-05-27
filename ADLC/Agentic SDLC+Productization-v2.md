## Flow Diagram

```mermaid
flowchart LR
    classDef planning   fill:#e7f1fa,stroke:#0066cc,color:#003366
    classDef assessment fill:#e8eaf6,stroke:#3949ab,color:#1a237e
    classDef execution        fill:#fde8e8,stroke:#ee0000,color:#660000
    classDef infra      fill:#fff3e0,stroke:#e65100,color:#4e2a00
    classDef approval   fill:#f3e5f5,stroke:#7b1fa2,color:#4a0072

    A[1. rfe-creator]:::planning
    A1[2. rfe-refine]:::planning
    B[3. strat-creator]:::planning
    B1[4. strat-refine]:::planning
    C1[5. epic-creator]:::planning
    D1[6. code-implementation]:::execution
    D2[7. packages-dependencies-configuration]:::execution
    D3[8. dockerfile-creation]:::execution
    D4[9. odh-repo-reator]:::infra
    D5[10. midstream-sync-enabler]:::infra
    subgraph OMA["onboarding-maturity-assessor"]
        E1[11. onboarding-info-generator]:::assessment
        E2[12. onboarding-info-validator]:::assessment
        E3[13. onboarding-readiness-rubric-score]:::assessment
        E4[14. onboarding-readiness-evaluator]:::assessment
    end
    F[15. devops-HITL-sign-off]:::approval
    G[16. create-component-onboarding-jira]:::planning
    H[17. component-onboarding]:::execution

    A --> A1 --> B --> B1 --> C1
    C1 --> D1
    C1 --> D2
    C1 --> D3
    C1 --> D4
    C1 --> D5
    D1 --> E1
    D2 --> E1
    D3 --> E1
    D4 --> E1
    D5 --> E1
    E1 --> E2 --> E3 --> E4 --> F --> G --> H 
```



### Legend


| Color     | Category                      | Stages         |
| --------- | ----------------------------- | -------------- |
| 🔵 Blue   | **Planning & Strategy**       | 1–5, 16        |
| 🔷 Indigo | **Assessment**                | 11, 12, 13, 14 |
| 🔴 Red    | **Development & Engineering** | 6, 7, 8, 17    |
| 🟠 Orange | **DevOps & Infrastructure**   | 9, 10          |
| 🟣 Purple | **Human Approval (HITL)**     | 15             |


## Stages


| #   | Stage                                     | Category        | Description                                               | Flow        |
| --- | ----------------------------------------- | --------------- | --------------------------------------------------------- | ----------- |
| 1   | **rfe-creator**                           | 🔵 Planning     | RFE (Requirement/Feature) creation                        | Sequential  |
| 2   | **rfe-refine**                            | 🔵 Planning     | RFE refinement                                            | Sequential  |
| 3   | **strat-creator**                         | 🔵 Planning     | Strategy creation                                         | Sequential  |
| 4   | **strat-refine**                          | 🔵 Planning     | Strategy refinement                                       | Sequential  |
| 5   | **epic-creator**                          | 🔵 Planning     | Epic decomposition into tasks                             | Sequential  |
| 6   | **code-implementation**                   | 🔴 Development  | Code implementation in upstream repos                     | Parallel    |
| 7   | **packages-dependencies-configuration**   | 🔴 Development  | Packages and dependencies configuration                   | Parallel    |
| 8   | **dockerfile-creation**                   | 🔴 Development  | Dockerfile creation                                       | Parallel    |
| 9   | **odh-repo-creator**                      | 🟠 DevOps/Infra | ODH repository creation                                   | Parallel    |
| 10  | **midstream-sync-enabler**                | 🟠 DevOps/Infra | Upstream to midstream sync enablement                     | Parallel    |
| 11  | **onboarding-info-generator**             | 🔷 Assessment   | Extract onboarding info from epics                        | Sequential  |
| 12  | **onboarding-info-validator**             | 🔷 Assessment   | Validate extracted onboarding info                        | Sequential  |
| 13  | **onboarding-readiness-rubric-score**     | 🔷 Assessment   | Score component readiness across rubric dimensions        | Sequential  |
| 14  | **onboarding-readiness-evaluator**        | 🔷 Assessment   | Evaluate readiness threshold and determine next action    | Sequential  |
| 15  | **devops-HITL-sign-off**                  | 🟣 Approval     | Human-in-the-loop review and approval                     | Sequential  |
| 16  | **create-component-onboarding-jira**      | 🔵 Planning     | Create onboarding Jira tickets (ODH + RHOAI)              | Sequential  |
| 17  | **component-onboarding**                  | 🔴 Development  | Execute component onboarding pipeline                     | Sequential  |


