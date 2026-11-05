FROM maven:3.9-eclipse-temurin-21
WORKDIR /workspace
RUN useradd --uid 65532 --create-home repofix
USER 65532:65532
CMD ["mvn", "test", "-q", "--offline"]
