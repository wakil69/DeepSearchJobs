FROM debezium/connect:2.7.3.Final

USER root

# Install Elasticsearch connector into the same directory as Debezium
COPY confluentinc-kafka-connect-elasticsearch-15.0.1.zip /tmp/es.zip
RUN unzip /tmp/es.zip -d /kafka/connect/debezium-connector-postgres && \
    rm /tmp/es.zip

# Add Groovy JSR223 engine (needed for Debezium scripting SMT)
RUN curl -sSL https://repo1.maven.org/maven2/org/codehaus/groovy/groovy/3.0.11/groovy-3.0.11.jar \
    -o /kafka/connect/debezium-connector-postgres/groovy-3.0.11.jar && \
    curl -sSL https://repo1.maven.org/maven2/org/codehaus/groovy/groovy-json/3.0.11/groovy-json-3.0.11.jar \
    -o /kafka/connect/debezium-connector-postgres/groovy-json-3.0.11.jar && \
    curl -sSL https://repo1.maven.org/maven2/org/codehaus/groovy/groovy-jsr223/3.0.11/groovy-jsr223-3.0.11.jar \
    -o /kafka/connect/debezium-connector-postgres/groovy-jsr223-3.0.11.jar

# # ==============================
# # Fix permissions
# # ==============================
RUN chown -R kafka:kafka /kafka/connect

USER kafka
