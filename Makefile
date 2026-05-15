# --- Configuration Variables ---
BASE ?= $(shell pwd)
# i.e Darwin / Linux
UNAME := $(shell uname)
# Lowercase - sane version
OS := $(shell echo "$(UNAME)" | tr '[:upper:]' '[:lower:]')

ARCH_QUERY := $(shell uname -m)
ifeq ($(ARCH_QUERY), x86_64)
	ARCH := amd64
else ifeq ($(ARCH_QUERY),$(filter $(ARCH_QUERY), arm64 aarch64))
	ARCH := arm64
else
	ARCH := $(ARCH_QUERY)
endif


KIND_CLUSTER_NAME ?= nokia-nautobot
KIND_CONFIG_REAL_LOC ?= build/kind-cluster.yaml
KIND_LAUNCH_CONFIG ?= /tmp/kind-config-$(KIND_CLUSTER_NAME).yaml

# Optional: Set API server address if you need to access it from outside Docker
# KIND_API_SERVER_ADDRESS ?= 127.0.0.1


# --- Tool Paths (now managed by Makefile) ---
TOOLS ?= $(BASE)/tools
KIND ?= $(TOOLS)/kind
KUBECTL ?= $(TOOLS)/kubectl
YQ ?= $(TOOLS)/yq
HELM ?= $(TOOLS)/helm
KPT ?= $(TOOLS)/kpt
K9S ?= $(TOOLS)/k9s
GH ?= $(TOOLS)/gh
CLAB ?= $(TOOLS)/clab # Added containerlab alias

# --- Git Repository Configuration ---
SRLINUX_IMAGE ?= registry.srlinux.dev/pub/nokia_srsim:25.10.R1
SRSIM_LICENSE_FILE ?= $(CLABS_DIR)/nautobot-bng/srsim-lic-25.txt

# Internal helper for output indentation
INDENT_OUT ?= sed 's/^/    /'
### Curl options:
CURL := curl --silent --fail --show-error

## Tools versions
### ---------------------------------------------------------------------------|
GH_VERSION ?= 2.67.0
HELM_VERSION ?= v3.17.0
KIND_VERSION ?= v0.29.0
KPT_VERSION ?= v1.0.0-beta.57
KUBECTL_VERSION ?= v1.33.1
K9S_VERSION ?= v0.32.4
YQ_VERSION ?= v4.42.1
CLAB_VERSION ?= 0.72.0

NAUTOBOT_IMAGE ?= pinrojas/nautobot:3.0-py3.13-nokia
NAUTOBOT_RELEASE ?= nautobot
NAUTOBOT_CHART ?= nautobot/nautobot
NAUTOBOT_VALUES ?= values-discovery.yaml
NAUTOBOT_SECRETS ?= nokia-secrets.yaml

PORT_FORWARD_PID_FILE ?= /tmp/nautobot-portforward.pid

### Tool Locations
### ---------------------------------------------------------------------------|
KIND_SRC ?= https://kind.sigs.k8s.io/dl/$(KIND_VERSION)/kind-$(OS)-$(ARCH)
KUBECTL_SRC ?= https://dl.k8s.io/release/$(KUBECTL_VERSION)/bin/$(OS)/$(ARCH)/kubectl
HELM_SRC ?= https://get.helm.sh/helm-$(HELM_VERSION)-$(OS)-$(ARCH).tar.gz
KPT_SRC ?= https://github.com/GoogleContainerTools/kpt/releases/download/$(KPT_VERSION)/kpt_$(OS)_$(ARCH)
K9S_SRC ?= https://github.com/derailed/k9s/releases/download/$(K9S_VERSION)/k9s_$(UNAME)_$(ARCH).tar.gz
YQ_SRC ?= https://github.com/mikefarah/yq/releases/download/$(YQ_VERSION)/yq_$(OS)_$(ARCH)
CLAB_SRC ?= https://github.com/srl-labs/containerlab/releases/download/v$(CLAB_VERSION)/containerlab_$(CLAB_VERSION)_$(OS)_$(ARCH).tar.gz

# GH_SRC needs special handling for OS/ARCH mapping
ifeq ($(OS),darwin)
    GH_OS_ARCH := macOS_$(ARCH)
    GH_EXT := zip
else
    GH_OS_ARCH := $(OS)_$(ARCH)
    GH_EXT := tar.gz
endif
GH_SRC ?= https://github.com/cli/cli/releases/download/v$(GH_VERSION)/gh_$(GH_VERSION)_$(GH_OS_ARCH).$(GH_EXT)

DOWNLOAD_TOOLS_LIST := $(KIND) $(KUBECTL) $(HELM) $(KPT) $(K9S) $(YQ) $(GH) $(CLAB) # Added CLAB

# --- Macros for tool downloading ---
define download-bin
    $(info --> INFO: Downloading $(2))
	if test ! -f $(1); then $(CURL) -Lo $(1) $(2) >/dev/null && chmod a+x $(1); fi
endef

define download-bin-from-archive
	$(info --> INFO: Downloading $(2))
	if test ! -f $(1); then $(CURL) -L --output - $(2) | tar -x$(5) $(if $(6),--strip-components $(6)) -C $(3) $(4) >/dev/null && chmod a+x $(1); fi
endef




.PHONY: try-nautobot
try-nautobot: check-tools cluster-up deploy-nautobot port-forward-nautobot

.PHONY: rebuild-image
rebuild-image: stop-port-forward-nautobot reload-image port-forward-nautobot

.PHONY: cluster-up
cluster-up: $(KIND_CONFIG_REAL_LOC) ## Bring up the KinD cluster
	@echo "--> KIND: Ensuring control-plane exists"
	@{ \
		cp $(KIND_CONFIG_REAL_LOC) $(KIND_LAUNCH_CONFIG) ;\
		if [ ! -z "$(KIND_API_SERVER_ADDRESS)" ]; then \
			echo "--> KIND: Setting API server address to $(KIND_API_SERVER_ADDRESS)" ;\
			$(YQ) eval ".networking.apiServerAddress = \"$(KIND_API_SERVER_ADDRESS)\"" -i $(KIND_LAUNCH_CONFIG) ;\
		fi ;\
		MATCHED=0 ;\
		for cluster_name in $$($(KIND) get clusters); do \
			if [[ "$${cluster_name}" == "$(KIND_CLUSTER_NAME)" ]]; then \
				MATCHED=1 ;\
			fi ;\
		done ;\
		if [[ "$${MATCHED}" == "0" ]]; then \
			echo "--> KIND: Creating cluster named $(KIND_CLUSTER_NAME)..." ;\
			$(KIND) create cluster --name $(KIND_CLUSTER_NAME) --config $(KIND_LAUNCH_CONFIG) 2>&1 | $(INDENT_OUT) ;\
		else \
			echo "--> KIND: Cluster named $(KIND_CLUSTER_NAME) already exists" ;\
		fi ;\
	}

.PHONY: cluster-wait-for-node-ready
cluster-wait-for-node-ready: ## Wait for the Kubernetes control plane node to be ready
	@echo "--> KIND: Waiting for k8s node to be ready"
	@{ \
		START=$$(date +%s) ;\
		$(KUBECTL) wait --for=condition=Ready node/$(KIND_CLUSTER_NAME)-control-plane --timeout=300s 2>&1 | $(INDENT_OUT) ;\
		echo "--> KIND: Node ready check took $$(( $$(date +%s) - $$START ))s" ;\
	}

.PHONY: delete-cluster
delete-cluster: ## Delete the KinD cluster
	@echo "--> KIND: Deleting cluster $(KIND_CLUSTER_NAME)..."
	@$(KIND) delete cluster --name $(KIND_CLUSTER_NAME) || true
	@rm -f $(KIND_LAUNCH_CONFIG)

.PHONY: check-tools
check-tools: $(KIND) $(KUBECTL) $(YQ) $(HELM) $(KPT) $(K9S) $(GH) $(CLAB) create-tool-aliases ## Ensure all required tools are present and aliased
	@echo "--> All required tools found or downloaded."

.PHONY: create-tool-aliases
create-tool-aliases: $(TOOLS) ## Create aliases for versioned binaries in the tools directory
	@echo "--> TOOLS: Creating aliases for versioned binaries"
	@{ \
		cd $(TOOLS) &&																	 \
		for binary_path in $(DOWNLOAD_TOOLS_LIST); do										 \
			binary_name=$$(basename $$binary_path)											;\
			tool_name=$$(echo $$binary_name | cut -d'-' -f1)							;\
			if [[ -f "$$binary_name" && -x "$$binary_name" && "$$binary_name" == *"-"* ]]; then	 \
				echo "    Creating alias: $$tool_name -> $$binary_name"						;\
				ln -sf "$$binary_name" "$$tool_name"											;\
			fi																			;\
		done																			;\
	}
	@echo "--> TOOLS: To add the tools to your path, paste this in your shell: export PATH=\$$PATH:$(TOOLS)"

.PHONY: help
help: ## Display this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# --- Tool Download Rules ---
$(KIND): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring kind is present in $(KIND))
	@$(call download-bin,$(KIND),$(KIND_SRC))

$(KUBECTL): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring kubectl is present in $(KUBECTL))
	@$(call download-bin,$(KUBECTL),$(KUBECTL_SRC))

$(HELM): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring helm is present in $(HELM))
	@$(call download-bin-from-archive,$(HELM),$(HELM_SRC),$(TOOLS),$(OS)-$(ARCH)/helm,z,1)

$(KPT): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring kpt is present in $(KPT))
	@$(call download-bin,$(KPT),$(KPT_SRC))

$(K9S): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring k9s is present in $(K9S))
	@$(call download-bin-from-archive,$(K9S),$(K9S_SRC),$(TOOLS),k9s,z)

$(YQ): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring yq is present in $(YQ))
	@$(call download-bin,$(YQ),$(YQ_SRC))

$(GH): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring gh is present in $(GH))
	@$(call download-bin-from-archive,$(GH),$(GH_SRC),$(TOOLS),gh_$(GH_VERSION)_$(GH_OS_ARCH)/bin/gh,z,2)

$(CLAB): | $(BASE) $(TOOLS) ; $(info --> TOOLS: Ensuring containerlab is present in $(CLAB))
	@if test ! -f $(CLAB); then \
		echo "    Downloading $(CLAB_SRC)..." ;\
		TEMP_DIR=$$(mktemp -d) ;\
		$(CURL) -L --output - $(CLAB_SRC) | tar -xz -C $$TEMP_DIR >/dev/null ;\
		mv $$TEMP_DIR/containerlab $(CLAB) ;\
		chmod a+x $(CLAB) ;\
		rm -rf $$TEMP_DIR ;\
	fi

$(BASE):
	@mkdir -p $(BASE)

$(TOOLS):
	@mkdir -p $(TOOLS)

#
$(KIND_CONFIG_REAL_LOC):
	@mkdir -p $(dir $(KIND_CONFIG_REAL_LOC)) # Ensure the build directory exists
	@echo "Creating default $(KIND_CONFIG_REAL_LOC)..."
	@echo "kind: Cluster" > $(KIND_CONFIG_REAL_LOC)
	@echo "apiVersion: kind.x-k8s.io/v1alpha4" >> $(KIND_CONFIG_REAL_LOC)
	@echo "nodes:" >> $(KIND_CONFIG_REAL_LOC)
	@echo "- role: control-plane" >> $(KIND_CONFIG_REAL_LOC)
	@echo "  kubeadmConfigPatches:" >> $(KIND_CONFIG_REAL_LOC)
	@echo "    - |" >> $(KIND_CONFIG_REAL_LOC)
	@echo "      kind: InitConfiguration" >> $(KIND_CONFIG_REAL_LOC)
	@echo "      nodeRegistration:" >> $(KIND_CONFIG_REAL_LOC)
	@echo "        kubeletExtraArgs:" >> $(KIND_CONFIG_REAL_LOC)
	@echo "          node-labels: \"ingress-ready=true\"" >> $(KIND_CONFIG_REAL_LOC)
	@echo "          authorization-mode: \"AlwaysAllow\"" >> $(KIND_CONFIG_REAL_LOC)
	@echo "    - |" >> $(KIND_CONFIG_REAL_LOC) # Add this new patch for ClusterConfiguration
	@echo "      kind: ClusterConfiguration" >> $(KIND_CONFIG_REAL_LOC)
	@echo "      apiServer:" >> $(KIND_CONFIG_REAL_LOC)
	@echo "        certSANs:" >> $(KIND_CONFIG_REAL_LOC)
	@echo "          - \"0.0.0.0\"" >> $(KIND_CONFIG_REAL_LOC) # Explicitly add 0.0.0.0 to SANs
	@echo "networking:" >> $(KIND_CONFIG_REAL_LOC)
	@echo "  apiServerPort: 6443" >> $(KIND_CONFIG_REAL_LOC)
	@echo "  podSubnet: \"10.244.0.0/16\"" >> $(KIND_CONFIG_REAL_LOC)
	@echo "  serviceSubnet: \"10.96.0.0/12\"" >> $(KIND_CONFIG_REAL_LOC)


.PHONY: install-nautobot-deps
install-nautobot-deps: ## Install Redis/Postgres + add Helm repo
	@echo "--> NAUTOBOT: Installing dependencies (Redis/Postgres + Helm repo)"
	@$(KUBECTL) apply -f postg-redis.yaml
	@$(HELM) repo add nautobot https://nautobot.github.io/helm-charts/ || true
	@$(HELM) repo update

.PHONY: deploy-nautobot
deploy-nautobot: install-nautobot-deps ## Build image, load into kind, deploy Nautobot
	@echo "--> NAUTOBOT: Building Docker image"
	@docker build -t $(NAUTOBOT_IMAGE) . --no-cache

	@echo "--> NAUTOBOT: Loading image into kind cluster"
	@$(KIND) load docker-image $(NAUTOBOT_IMAGE) --name $(KIND_CLUSTER_NAME)

	@echo "--> NAUTOBOT: Loading Secrets"
	@$(KUBECTL) apply -f $(NAUTOBOT_SECRETS)

	@echo "--> NAUTOBOT: Installing Helm release"
	@$(HELM) install $(NAUTOBOT_RELEASE) $(NAUTOBOT_CHART) -f $(NAUTOBOT_VALUES)


.PHONY: reload-image
reload-image:
	@echo "--> NAUTOBOT: Remove nautobot deployment"
	@$(HELM) delete $(NAUTOBOT_RELEASE)

	@echo "--> NAUTOBOT: Building Docker image"
	@docker build -t $(NAUTOBOT_IMAGE) . --no-cache

	@echo "--> NAUTOBOT: Loading image into kind cluster"
	@$(KIND) load docker-image $(NAUTOBOT_IMAGE) --name $(KIND_CLUSTER_NAME)

	@echo "--> NAUTOBOT: Installing Helm release"
	@$(HELM) install $(NAUTOBOT_RELEASE) $(NAUTOBOT_CHART) -f $(NAUTOBOT_VALUES)


.PHONY: port-forward-nautobot
port-forward-nautobot: ## Run Nautobot port-forward in background
	@echo "--> NAUTOBOT: Waiting for service endpoints to be ready..."
	@$(KUBECTL) wait --namespace default --for=condition=ready pod -l app.kubernetes.io/name=nautobot --timeout=120s

	@echo "--> NAUTOBOT: Starting port-forward in background"
	@nohup $(KUBECTL) port-forward \
		--namespace default svc/nautobot-default \
		--address 0.0.0.0 8443:443 \
		> /tmp/nautobot-portforward.log 2>&1 & echo $$! > $(PORT_FORWARD_PID_FILE)
	@echo "--> NAUTOBOT: Port-forward PID stored in $(PORT_FORWARD_PID_FILE)"


.PHONY: stop-port-forward-nautobot
stop-port-forward-nautobot:
	@echo "--> NAUTOBOT: Stopping port-forward"
	@if [ -f $(PORT_FORWARD_PID_FILE) ]; then \
		kill $$(cat $(PORT_FORWARD_PID_FILE)) || true ;\
		rm -f $(PORT_FORWARD_PID_FILE) ;\
	else \
		echo "No PID file found" ;\
	fi	