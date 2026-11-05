FROM node:22-slim
WORKDIR /workspace
USER 65532:65532
CMD ["npm", "test", "--", "--run"]
