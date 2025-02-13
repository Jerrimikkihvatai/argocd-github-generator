# ArgoCD GitHub ApplicationSet Generator

## Problem
Reference: 
- https://github.com/argoproj/argo-cd/issues/9413
- https://github.com/argoproj/argo-cd/pull/14465

The native ArgoCD ApplicationSet SCM generator consumes the GitHub API rate limit much faster than it resets.  
This problem is particularly relevant for large organizations with many repositories.

## Solution
I have written a simple [ArgoCD generator](https://argo-cd.readthedocs.io/en/latest/operator-manual/applicationset/Generators-Plugin/) that monitors only a specified repository and its branches. It utilizes the API quota in a much more efficient manner.

## Note
- This plugin currently does not support GitHub App authentication. Only personal access tokens are supported.
- This plugin returns normalized branch names, which are safe to use in DNS and application names.
- Regular expressions are not fully supported. You can only use symbols that are allowed in HTTP requests (e.g., `*`, `^`).
- Feel free to fork this project and add any required features.

---
## Installation
0) Try plugin locally
```bash
pip3 install -r requirements.txt
PLUGIN_TOKEN="123" GITHUB_TOKEN="github_pat_123..." LOG_LEVEL="DEBUG" python3 /plugin/main.py 
```
```bash
curl -X POST 'http://localhost:4355/api/v1/getparams.execute' \
  --header 'Content-Type: text/plain' \
  --data-raw '{
  "applicationSetName": "fake-appset",
  "input": {
    "parameters": {
      "repositoryOwner": "yourOrg",
      "repositoryName": "repoName",
      "branchMatch": "^master,^feature-*"
    }
  }
}' \
  --header 'Authorization: Bearer 123'
```
The plugin will return a list with branches and their normalized names
```json
{
  "output": {
    "parameters": [
      {
        "total": 1,
        "branches": [
          {
            "name": "master",
            "name_normalized": "master"
          }
        ]
      }
    ]
  }
}
```
1) Build docker image and push it to your org registry
```bash
docker buildx build --platform=linux/amd64 -t <your-image-tag> .
```
2) Create these objects in your argocd namespace:
- A Confgimap that defines plugin. Note that plugin name in appset should match configmap name. Also don't forget to add a plugin token to argocd secret [as it specified here](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/#sensitive-data-and-sso-client-secrets) 
- A Deployment with plugin and its service
- A Secret with tokens (only to pass values to deployment)


```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-appset-plugin
  namespace: argocd
data:
  token: '$plugin.appset_plugin.token'
  baseUrl: "http://argocd-appset-plugin.argocd.svc.cluster.local"
  requestTimeout: "30"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-appset-plugin
  namespace: argocd
spec:
  template:
    spec:
      nodeSelector:
        node-group: test-argocd
      containers:
        - name: plugin
          image:  <your-image-tag>
          command: ["python3", "/plugin/main.py"]
          env:
          - name: LOG_LEVEL
            value: INFO
          - name: PLUGIN_TOKEN
            valueFrom:
              secretKeyRef:
                name: argocd-appset-plugin
                key: PLUGIN_TOKEN
          - name: GITHUB_TOKEN
            valueFrom:
              secretKeyRef:
                name: argocd-appset-plugin
                key: GITHUB_TOKEN
          resources:
            limits:
              cpu: 500m
              memory: 500Mi
            requests:
              cpu: 250m
              memory: 250Mi
          ports:
            - containerPort: 4355
              name: http
---
apiVersion: v1
kind: Service
metadata:
  name: argocd-appset-plugin
  namespace: argocd
spec:
  ports:
  - name: http
    port: 80
    targetPort: 4355
---
apiVersion: v1
kind: Secret
metadata:
  name: argocd-appset-plugin
  namespace: argocd
data:
  GITHUB_TOKEN: <your-github-token>
  PLUGIN_TOKEN: <your-token-for-plugin>
type: Opaque
```
You can read more about installation process [here](https://argo-cd.readthedocs.io/en/latest/proposals/applicationset-plugin-generator/)

3) Spin up your ApplicationSet
```yaml
---
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: Myapp
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
  # Note the matrix generator
  - matrix:
      generators:
      - plugin:
          configMapRef:
            name: argocd-appset-plugin
          requeueAfterSeconds: 30  # Tune refresh interval on demand
          input:
            parameters:
              repositoryOwner: "yourOrg"
              repositoryName: "repoName"
              branchMatch: "^master,^feature-*"
      - list:
          elementsYaml: "{{ .branches | toJson }}"
  template:
    metadata:
      name: "{{ .name_normalized }}-my-app"
      namespace: argocd
      labels:
        service: my-app
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      project: myProject
      source:
        path: myHelmChart
        repoURL: https://github.com:myorg/myrepo.git
        targetRevision: master
        helm:
          valuesObject:
            # Values from our generator
            branch: "{{ .name }}"
            brnchNameNormalized: "{{ .name_normalized }}"
```