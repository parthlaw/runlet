# Conventions

## Adding a Custom Step

A step is a class that inherits from the base step abstraction and implements a single method that accepts a read-only runtime context and returns a JSON-serializable dict. The method must not modify any shared state outside the context.

Config accessors provided by the base class should be used to read step-specific configuration rather than accessing the raw config dict directly.

Optional lifecycle methods (`validate_config`, `teardown`) may be overridden when needed.

## Registering a Custom Artifact Store

An artifact store is a class that inherits from the artifact store abstraction and implements its upload/download/existence/deletion contract. It is registered under a string key before the runner is built. The pipeline config references the store by that key.

Custom stores must handle their own URI scheme and must guarantee that a URI produced by `upload_json` or `upload_file` is resolvable by the corresponding `download_*` method on the same or a differently-constructed instance pointing to the same backing storage.

## Registering a Custom Metastore

A metastore is a class that inherits from the run metastore abstraction and implements the run and step lifecycle recording contract. It is registered under a string key before the runner is built.

Custom metastores must be thread-safe: the runner may call metastore methods concurrently from multiple step-execution threads.

## Step Output Contract

Every step must return a JSON-serializable dict. Returning `None`, a non-dict, or a dict containing non-JSON-serializable values will cause a runtime error. If a step produces large data (files, arrays, binary payloads), the data must be written to the artifact store and only its URI placed in the output dict.

## Large Data Convention

Steps that produce data too large to hold in memory or in a JSON dict write it to the artifact store via the context's store reference and place the resulting URI in the output dict. Downstream steps retrieve the data by reading that URI from the upstream step's output and calling the corresponding download method.

## Optional Dependencies

Optional integrations are gated behind install extras. A step or store that requires an optional dependency must document which extra to install. The package does not import optional dependencies at load time — they are resolved on first use. Import errors for optional dependencies will surface at runtime, not at package import time.

## Extending the Registry

Both the artifact store registry and the metastore registry accept new entries at any point before the runner is built. Registration is global within a process. There is no unregister operation — registrations persist for the lifetime of the process.
