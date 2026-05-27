## Flow Diagram

```mermaid
flowchart LR
    classDef planning   fill:#e7f1fa,stroke:#0066cc,color:#003366
    classDef assessment fill:#e8eaf6,stroke:#3949ab,color:#1a237e
    classDef execution        fill:#fde8e8,stroke:#ee0000,color:#660000
    classDef infra      fill:#fff3e0,stroke:#e65100,color:#4e2a00
    classDef approval   fill:#f3e5f5,stroke:#7b1fa2,color:#4a0072

    A[1. rfe-creator]:::planning
    A1[1. rfe-refine]:::planning
    B[2. strat-creator]:::planning
    B1[2. strat-refine]:::planning
    C1[3. epic-creator]:::planning
    D1[5. code-implementation]:::execution
    D2[6. packages-dependencies-configuration]:::execution
    D3[7. dockerfile-creation]:::execution
    D4[8. odh-repo-reator]:::infra
    D5[9. midstream-sync-enabler]:::infra
    E1[4. onboarding-info-generator]:::assessment
    E2[4. onboarding-info-validator]:::assessment
    E3[4. onboarding-maturity-assessor]:::assessment
    F[11. devops-HITL-sign-off]:::approval
    G[12. create-component-onboarding-jira]:::planning
    H[13. component-onboarding]:::execution

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
    E1 --> E2 --> E3 --> F --> G --> H 
```



### Legend


| Color     | Category                      | Stages               |
| --------- | ----------------------------- | -------------------- |
| 🔵 Blue   | **Planning & Strategy**       | 1, 2, 3              |
| 🔷 Indigo | **Assessment**                | 4 *(new)*            |
| 🔴 Red    | **Development & Engineering** | 5, 6, 7, 13, 18      |
| 🟠 Orange | **DevOps & Infrastructure**   | 8, 9, 10, 12, 15, 17 |
| 🟣 Purple | **Human Approval (HITL)**     | 11, 16               |
| 🔷 Teal   | **Quality & Validation**      | 14, 19               |
| 🟢 Green  | **Release**                   | 20                   |


## Stages


| #   | Stage                                         | Category        | Description                                                            | Change             |
| --- | --------------------------------------------- | --------------- | ---------------------------------------------------------------------- | ------------------ |
| 1   | **RFE Creator**                               | 🔵 Planning     | Requirement/Feature creation                                           | —                  |
| 2   | **Strat Creator**                             | 🔵 Planning     | Strategy creation                                                      | —                  |
| 3   | **Epic Decomposer**                           | 🔵 Planning     | Epic decomposition into tasks                                          | —                  |
| 4   | **rhoai-maturity-assessor**                   | 🔷 Assessment   | Assess component maturity and readiness before engineering work begins | **New**            |
| 5   | **Code Implementation in upstream repos**     | 🔴 Development  | Implementation/development in upstream                                 | Parallel *(was 4)* |
| 6   | **Packages+Dependencies Generator**           | 🔴 Development  | Identify packages and dependencies                                     | Parallel *(was 5)* |
| 7   | **Dockerfile Creator**                        | 🔴 Development  | Create/update Dockerfiles                                              | Parallel *(was 6)* |
| 8   | **ODH Repo Creator**                          | 🟠 DevOps/Infra | Create ODH repository                                                  | Parallel *(was 7)* |
| 9   | **Upstream to Midstream Sync Enabler**        | 🟠 DevOps/Infra | Enable sync from upstream to midstream                                 | Parallel *(was 8)* |
| 10  | **ODH Component Onboarding Info Generator**   | 🟠 DevOps/Infra | Generate onboarding details for ODH                                    | *(was 9)*          |
| 11  | **DevOps HITL Sign off**                      | 🟣 Approval     | Human-in-the-loop approval (ODH)                                       | *(was 10)*         |
| 12  | **ODH Component Onboarding**                  | 🟠 DevOps/Infra | Onboard component to ODH platform                                      | *(was 11)*         |
| 13  | **ODH Build**                                 | 🔴 Development  | Build ODH component                                                    | *(was 12)*         |
| 14  | **Q&E / Validation**                          | 🔷 Quality      | Quality Engineering validation (ODH)                                   | *(was 13)*         |
| 15  | **RHOAI Component Onboarding Info Generator** | 🟠 DevOps/Infra | Generate onboarding details for RHOAI                                  | *(was 14)*         |
| 16  | **DevOps HITL Sign off**                      | 🟣 Approval     | Human-in-the-loop approval (RHOAI)                                     | *(was 15)*         |
| 17  | **RHOAI Component Onboarding**                | 🟠 DevOps/Infra | Onboard component to RHOAI platform                                    | *(was 16)*         |
| 18  | **RHOAI Build**                               | 🔴 Development  | Build RHOAI component                                                  | *(was 17)*         |
| 19  | **Q&E / Validation**                          | 🔷 Quality      | Quality Engineering validation (RHOAI)                                 | *(was 18)*         |
| 20  | **Release**                                   | 🟢 Release      | Final release                                                          | *(was 19)*         |


