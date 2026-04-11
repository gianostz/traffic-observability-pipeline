FROM apache/spark:3.5.8-scala2.12-java11-python3-r-ubuntu

USER root

ARG ICEBERG_VERSION=1.10.1
ARG SPARK_VERSION=3.5.8
ARG POSTGRES_JDBC_VERSION=42.7.10

# Iceberg runtime (fat JAR — bundles all Iceberg dependencies)
RUN curl -fSL -o $SPARK_HOME/jars/iceberg-spark-runtime.jar \
    "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/${ICEBERG_VERSION}/iceberg-spark-runtime-3.5_2.12-${ICEBERG_VERSION}.jar"

# PostgreSQL JDBC driver (standalone JAR — needed in B4, pre-installed now)
RUN curl -fSL -o $SPARK_HOME/jars/postgresql.jar \
    "https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRES_JDBC_VERSION}/postgresql-${POSTGRES_JDBC_VERSION}.jar"

# Kafka connector + transitives resolved by Ivy at build time
# Per CLAUDE.md: do NOT pin kafka-clients or commons-pool2 explicitly
RUN echo ':quit' | $SPARK_HOME/bin/spark-shell \
    --packages "org.apache.spark:spark-sql-kafka-0-10_2.12:${SPARK_VERSION}" \
    2>&1 && \
    cp -n ~/.ivy2/jars/*.jar $SPARK_HOME/jars/ 2>/dev/null; \
    rm -rf ~/.ivy2 ~/.m2

COPY src/ /app/src/
COPY data/ /app/data/

# Ensure warehouse and checkpoint dirs are writable by the spark user (UID 185)
RUN mkdir -p /opt/warehouse /opt/checkpoints && \
    chown -R spark:spark /opt/warehouse /opt/checkpoints

USER spark
WORKDIR /app

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["/opt/spark/bin/spark-submit", "--master", "local[*]", \
     "/app/src/streaming/stream_processor.py"]
